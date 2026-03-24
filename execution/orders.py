"""
execution/orders.py

Places bracket orders on IBKR for MES futures.

A bracket order is three linked orders submitted together:
    1. Parent  — Market order (entry)
    2. Child 1 — Limit order  (take profit)
    3. Child 2 — Stop order   (stop loss)

If either child fills, IBKR automatically cancels the other.
This means once we enter, exits are handled entirely by IBKR —
the bot does not need to babysit the position.
"""

import logging
from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder

from config import settings

logger = logging.getLogger(__name__)


def get_mes_contract(ib: IB) -> Future:
    """
    Return the front-month MES contract.
    Queries IBKR for all active MES contracts and picks the nearest expiry.
    """
    contract = Future(symbol="MES", exchange="CME", currency="USD")
    details  = ib.reqContractDetails(contract)

    if not details:
        raise RuntimeError("No MES contract details returned from IBKR. "
                           "Check TWS/Gateway is running and API is enabled.")

    # Sort by expiry, take the nearest (front month)
    details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
    front = details[0].contract
    logger.info(f"MES front-month contract: {front.localSymbol} "
                f"(expires {front.lastTradeDateOrContractMonth})")
    return front


def place_bracket_order(
    ib:         IB,
    contracts:  int,
    sl_price:   float,
    tp_price:   float,
    direction:  int = 1,        # 1 = long, -1 = short
) -> list:
    """
    Place a bracket order for MES.

    Args:
        ib         : active IB connection
        contracts  : number of MES contracts
        sl_price   : stop loss price (hard stop)
        tp_price   : take profit price (limit)
        direction  : 1 for long, -1 for short

    Returns:
        List of ib_insync Trade objects [parent, take_profit, stop_loss]
    """
    action     = "BUY"  if direction ==  1 else "SELL"
    exit_action = "SELL" if direction ==  1 else "BUY"

    contract = get_mes_contract(ib)

    # ── Parent (market entry) ────────────────────────────────────────────
    parent           = MarketOrder(action, contracts)
    parent.orderId   = ib.client.getReqId()
    parent.transmit  = False      # hold — don't send until children are ready
    parent.account   = ""         # uses default account

    # ── Take profit (limit order) ────────────────────────────────────────
    tp              = LimitOrder(exit_action, contracts, round(tp_price, 2))
    tp.orderId      = ib.client.getReqId()
    tp.parentId     = parent.orderId
    tp.transmit     = False

    # ── Stop loss (stop order) ────────────────────────────────────────────
    sl              = StopOrder(exit_action, contracts, round(sl_price, 2))
    sl.orderId      = ib.client.getReqId()
    sl.parentId     = parent.orderId
    sl.transmit     = True        # transmit=True on last child sends all three

    logger.info(
        f"Placing bracket order | MES x{contracts} {action} | "
        f"SL={sl_price:.2f}  TP={tp_price:.2f}"
    )

    trades = []
    for order in [parent, tp, sl]:
        trades.append(ib.placeOrder(contract, order))

    ib.sleep(1)  # allow IBKR to acknowledge

    # Log order IDs for tracking
    for t in trades:
        logger.info(f"  Order submitted: {t.order.orderType} "
                    f"orderId={t.order.orderId} "
                    f"status={t.orderStatus.status}")

    return trades


def cancel_all_mes_orders(ib: IB) -> None:
    """Cancel all open MES orders. Used for emergency stop or cleanup."""
    open_orders = ib.openOrders()
    cancelled = 0
    for order in open_orders:
        if "MES" in str(order):
            ib.cancelOrder(order)
            cancelled += 1
    if cancelled:
        logger.warning(f"Cancelled {cancelled} open MES orders")


def get_open_mes_position(ib: IB) -> int:
    """
    Return current MES position size (positive = long, negative = short, 0 = flat).
    """
    for pos in ib.positions():
        if pos.contract.symbol == "MES":
            return int(pos.position)
    return 0

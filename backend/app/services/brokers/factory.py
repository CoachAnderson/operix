from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.models import Bot, ExchangeCredential, Market, Venue
from app.services import b3, ctrader_auth
from app.services.brokers.base import Broker, BrokerError
from app.services.brokers.binance import BinanceClient
from app.services.brokers.ctrader import CTraderBroker, get_connection
from app.services.brokers.mt5 import MT5Broker
from app.services.brokers.paper import PaperAccount, PaperBroker


def credential_aad(cred: ExchangeCredential) -> str:
    # Amarra o texto cifrado ao dono e à credencial: copiar o blob para outra linha não funciona.
    return f"{cred.user_id}:{cred.id}"


def decrypt_credential(cred: ExchangeCredential) -> tuple[str, str]:
    aad = credential_aad(cred)
    return crypto.decrypt(cred.api_key_enc, aad), crypto.decrypt(cred.api_secret_enc, aad)


async def ctrader_broker(db: AsyncSession, cred: ExchangeCredential) -> CTraderBroker:
    client_id, secret = ctrader_auth.app_keys(cred)
    token = await ctrader_auth.access_token(db, cred)
    conn = await get_connection(cred.venue == Venue.live, client_id, secret)
    return CTraderBroker(conn, int(cred.external_account_id or 0), token, cred.venue.value)


async def _credential(db: AsyncSession, bot: Bot) -> ExchangeCredential:
    if not bot.credential_id:
        raise BrokerError("Robô sem credencial de corretora")
    cred = await db.get(ExchangeCredential, bot.credential_id)
    if not cred or cred.user_id != bot.user_id:
        raise BrokerError("Credencial não encontrada")
    if not cred.verified_at:
        raise BrokerError("Credencial ainda não verificada")
    return cred


async def broker_for_bot(db: AsyncSession, bot: Bot) -> Broker:
    if bot.market == Market.b3:
        # Futuros da B3: o MetaTrader 5 do cliente (via conector) é a fonte de cotações também na simulação.
        cred = await _credential(db, bot)
        if cred.exchange != "mt5":
            raise BrokerError("Robô da B3 precisa de uma conexão com o MetaTrader 5")
        broker = MT5Broker(cred.id, cred.venue.value)
        if bot.venue == Venue.paper:
            f = b3.info(bot.symbol)
            return PaperBroker(broker, PaperAccount(bot.paper_quote_balance, Decimal("0")), fee_rate=f.fee_rate, slippage_bps=f.slippage_bps, margin=True)
        if cred.venue != bot.venue:
            raise BrokerError("A conta do MetaTrader 5 não corresponde ao ambiente do robô (demo × real)")
        if not cred.can_trade:
            raise BrokerError("Negociação automática desligada no MetaTrader 5 (botão Algo Trading) ou conta sem permissão")
        return broker

    if bot.market == Market.forex:
        # Forex usa a conta cTrader do cliente também na simulação (para cotações e regras do símbolo).
        cred = await _credential(db, bot)
        if cred.exchange != "ctrader":
            raise BrokerError("Robô de forex precisa de uma conta cTrader")
        broker = await ctrader_broker(db, cred)
        if bot.venue == Venue.paper:
            # Taxa ~US$ 3 por lado a cada 100 mil unidades e 0,005% de slippage: ordem de grandeza de conta ECN.
            return PaperBroker(broker, PaperAccount(bot.paper_quote_balance, Decimal("0")), fee_rate=0.00003, slippage_bps=0.5, margin=True)
        if cred.venue != bot.venue:
            raise BrokerError("A conta cTrader não corresponde ao ambiente do robô (demo × real)")
        if not cred.can_trade:
            raise BrokerError("O token desta conta cTrader não permite negociar (escopo só de leitura)")
        return broker

    if bot.venue == Venue.paper:
        return PaperBroker(BinanceClient("live"), PaperAccount(bot.paper_quote_balance, bot.paper_base_balance))
    cred = await _credential(db, bot)
    if cred.exchange != "binance":
        raise BrokerError("Robô de cripto precisa de uma chave da Binance")
    if cred.venue != bot.venue:
        raise BrokerError("Credencial não corresponde ao ambiente do robô")
    if not cred.can_trade:
        raise BrokerError("Credencial sem permissão de negociação verificada")
    key, secret = decrypt_credential(cred)
    return BinanceClient(bot.venue.value, key, secret)


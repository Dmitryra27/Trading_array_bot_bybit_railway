import os
import time
import pandas as pd
import numpy as np
from pybit.unified_trading import HTTP
from collections import deque
from dotenv import load_dotenv
import asyncio
import json
from typing import Dict, Any, List
import logging
from pydantic import BaseModel
# Настройка логирования без эмодзи
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
# Загрузка переменных окружения
load_dotenv()
class PasswordCheck(BaseModel):
    password: str
class AssetConfigUpdate(BaseModel):
    symbol: str
    enabled: bool = None
    n_percent: float = None
    k_percent: float = None
    max_position: float = None
class ConfigUpdate(BaseModel):
    buy_percent: float = None
    sell_percent: float = None
    price_offset: float = None
    min_lot_usd: float = None
class MultiAssetTradingBot:
    def __init__(self):
        # Конфигурация API
        self.api_key = os.getenv('API_KEY')
        self.api_secret = os.getenv('API_SECRET')
        self.admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        if not self.api_key or not self.api_secret:
            raise ValueError("Необходимо установить API_KEY и API_SECRET в .env файле")
        # Подключение к Bybit
        try:
            self.session = HTTP(
                testnet=False,
                api_key=self.api_key,
                api_secret=self.api_secret
            )
            logger.info("Подключение к Bybit установлено")
        except Exception as e:
            logger.error(f"Ошибка подключения к Bybit: {e}")
            raise
        # Конфигурация бота
        self.buy_percent = 30  # Покупаем 30% от позиции
        self.sell_percent = 35  # Продаем 35% от позиции
        self.price_offset = 0.3  # Отступ 0.3% для limit ордеров
        self.order_ttl = 2 * 3600  # 2 часа TTL ордера
        self.min_lot_usd = 5.0  # Минимальный лот $5
        # Состояние бота
        self.trading_active = False
        self.assets_data = {}  # Данные по каждому активу
        self.websocket_listeners = set()
        self.trade_history = deque(maxlen=1000)  # История сделок
        self.account_balance = 0  # Баланс счета
        self.account_equity = 0   # Эквити счета
        self.account_available_margin = 0  # Доступная маржа
        # Загрузка конфигурации активов
        self.load_assets_config()
    def load_assets_config(self):
        """Загрузка конфигурации активов"""
        # Конфигурация активов
        self.assets_config = {
            'SENDUSDT': {'n_percent': 11, 'k_percent': 9, 'enabled': True, 'max_position': 30.0},
            'AVAXUSDT': {'n_percent': 3, 'k_percent': 1, 'enabled': True, 'max_position': 1.0},
            'HOMEUSDT': {'n_percent': 3, 'k_percent': 2, 'enabled': True, 'max_position': 390.0},
            'XRPUSDT': {'n_percent': 11, 'k_percent': 9, 'enabled': True, 'max_position': 6.0},
            'DOGEUSDT': {'n_percent': 3, 'k_percent': 1, 'enabled': True, 'max_position': 70.0},
            'HYPEUSDT': {'n_percent': 3, 'k_percent': 2, 'enabled': True, 'max_position': 0.34},
            'HIFIUSDT': {'n_percent': 3, 'k_percent': 2, 'enabled': False, 'max_position': 216.0},
            'ALUUSDT': {'n_percent': 1, 'k_percent': 1, 'enabled': True, 'max_position': 270.0},
            'SAROSUSDT': {'n_percent': 8, 'k_percent': 11, 'enabled': True, 'max_position': 42.0},
            'MUSDT': {'n_percent': 4, 'k_percent': 3, 'enabled': True, 'max_position': 15.0},
            'MYXUSDT': {'n_percent': 13, 'k_percent': 14, 'enabled': True, 'max_position': 12.0},
            'OGUSDT': {'n_percent': 13, 'k_percent': 1, 'enabled': True, 'max_position': 1.2},
            'ORDERUSDT': {'n_percent': 10, 'k_percent': 5, 'enabled': True, 'max_position': 108.0},
            'OMNIUSDT': {'n_percent': 10, 'k_percent': 6, 'enabled': True, 'max_position': 5.0},
            'CYBERUSDT': {'n_percent': 9, 'k_percent': 6, 'enabled': True, 'max_position': 9.0},
            'IDEXUSDT': {'n_percent': 14, 'k_percent': 6, 'enabled': True, 'max_position': 180.0},
            'API3USDT': {'n_percent': 13, 'k_percent': 2, 'enabled': True, 'max_position': 15.0},
            'MAVUSDT': {'n_percent': 11, 'k_percent': 4, 'enabled': True, 'max_position': 200.0},
            'REXUSDT': {'n_percent': 10, 'k_percent': 2, 'enabled': True, 'max_position': 330.0},
            'CROUSDT': {'n_percent': 14, 'k_percent': 1, 'enabled': True, 'max_position': 55.0},
            'DOLOUSDT': {'n_percent': 15, 'k_percent': 3, 'enabled': True, 'max_position': 80.0},
            'SIRENUSDT': {'n_percent': 15, 'k_percent': 2, 'enabled': True, 'max_position': 160.0},
        }
        # Инициализация данных по каждому активу
        for symbol in self.assets_config.keys():
            self.assets_data[symbol] = {
                'last_price': 0,
                'position': 0,
                'avg_price': 0,
                'reference_price': 0,
                'active_order': None,
                'last_update': time.time(),
                'error_message': '',
                'min_lot': 0,
                'max_lot': 0,
                'lot_size_step': 0.1,
                'buy_price_level': 0,
                'sell_price_level': 0,
                'last_trade_time': 0,
                'daily_pnl': 0,
                'weekly_pnl': 0
            }
        logger.info(f"Загружено конфигураций для {len(self.assets_config)} активов")
    def calculate_asset_lots(self, symbol: str) -> Dict[str, float]:
        """Рассчитать минимальный и максимальный лот для актива"""
        try:
            # Получаем информацию об инструменте
            response = self.session.get_instruments_info(
                category="linear",
                symbol=symbol
            )
            if response['result']['list']:
                instrument = response['result']['list'][0]
                # Получаем минимальный шаг лота
                lot_size_filter = instrument.get('lotSizeFilter', {})
                lot_size_step = float(lot_size_filter.get('minOrderQty', 0.1))
                # Получаем текущую цену
                current_price = self.get_asset_price(symbol)
                if current_price <= 0:
                    current_price = 1.0
                # Рассчитываем минимальный лот ($5)
                min_lot = max(self.min_lot_usd / current_price, lot_size_step)
                # Округляем до шага лота
                min_lot = round(min_lot / lot_size_step) * lot_size_step
                # Максимальный лот = минимальный * 3
                max_lot = min_lot * 3
                logger.info(f"[{symbol}] min_lot=${min_lot*current_price:.2f} ({min_lot}), max_lot=${max_lot*current_price:.2f} ({max_lot})")
                return {
                    'min_lot': min_lot,
                    'max_lot': max_lot,
                    'lot_size_step': lot_size_step,
                    'current_price': current_price
                }
        except Exception as e:
            logger.error(f"Ошибка расчета лотов для {symbol}: {e}")
            return {
                'min_lot': 0.1,
                'max_lot': 0.3,
                'lot_size_step': 0.1,
                'current_price': 1.0
            }
    def initialize_asset_lots(self):
        """Инициализировать лоты для всех активов"""
        logger.info("Инициализация лотов для всех активов...")
        for symbol in self.assets_config.keys():
            lots = self.calculate_asset_lots(symbol)
            self.assets_data[symbol]['min_lot'] = round(lots['min_lot'], 1)
            self.assets_data[symbol]['max_lot'] = round(lots['max_lot'], 1)
            self.assets_data[symbol]['lot_size_step'] = lots['lot_size_step']
            self.assets_data[symbol]['last_price'] = lots['current_price']
        logger.info("Инициализация лотов завершена")
    def get_asset_price(self, symbol: str) -> float:
        """Получить текущую цену актива"""
        try:
            response = self.session.get_tickers(category="linear", symbol=symbol)
            if response['result']['list']:
                return float(response['result']['list'][0]['lastPrice'])
            return 0
        except Exception as e:
            logger.error(f"Ошибка получения цены для {symbol}: {e}")
            return 0
    def get_account_balance(self):
        """Получить баланс счета"""
        try:
            response = self.session.get_wallet_balance(accountType="UNIFIED")
            if response['result']['list']:
                wallet = response['result']['list'][0]
                self.account_balance = float(wallet['totalWalletBalance']) if wallet['totalWalletBalance'] else 0
                self.account_equity = float(wallet['totalEquity']) if wallet['totalEquity'] else 0
                self.account_available_margin = float(wallet['totalAvailableBalance']) if wallet['totalAvailableBalance'] else 0
                logger.info(f"Баланс: ${self.account_balance:.2f}, Эквити: ${self.account_equity:.2f}, Доступно: ${self.account_available_margin:.2f}")
        except Exception as e:
            logger.error(f"Ошибка получения баланса: {e}")
    def get_asset_position(self, symbol: str) -> Dict[str, Any]:
        """Получить позицию по активу"""
        try:
            response = self.session.get_positions(category="linear", symbol=symbol)
            if response['result']['list']:
                pos_data = response['result']['list'][0]
                position = float(pos_data['size']) if pos_data['size'] else 0
                position_side = pos_data.get('side', '')
                # Корректируем знак позиции
                if position_side == 'Sell' and position > 0:
                    position = -position
                return {
                    'position': position,
                    'avg_price': float(pos_data['avgPrice']) if pos_data['avgPrice'] else 0,
                    'pnl': float(pos_data['unrealisedPnl']) if pos_data['unrealisedPnl'] else 0,
                    'side': position_side
                }
            return {'position': 0, 'avg_price': 0, 'pnl': 0, 'side': ''}
        except Exception as e:
            logger.error(f"Ошибка получения позиции для {symbol}: {e}")
            return {'position': 0, 'avg_price': 0, 'pnl': 0, 'side': ''}
    def place_limit_order(self, symbol: str, side: str, qty: float, price: float) -> str:
        """Разместить limit ордер"""
        try:
            logger.info(f"[{symbol}] Попытка {side} ордера: {qty} по цене {price}")
            # Округляем количество до шага лота (1 знак после запятой)
            lot_size_step = self.assets_data[symbol].get('lot_size_step', 0.1)
            qty = round(qty, 1)
            qty = max(qty, lot_size_step)
            # Определяем positionIdx для уменьшения позиции
            position_idx = 0  # По умолчанию
            position_side = self.assets_data[symbol].get('position_side', '')
            order = self.session.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Limit",
                qty=str(round(qty, 1)),
                price=str(round(price, 4)),
                timeInForce="GTC",
                positionIdx=position_idx,
                reduceOnly=side == "Sell" and self.assets_data[symbol]['position'] > 0 or
                           side == "Buy" and self.assets_data[symbol]['position'] < 0
            )
            if 'result' in order and 'orderId' in order['result']:
                order_id = order['result']['orderId']
                logger.info(f"[{symbol}] Ордер {side} размещен: {order_id}")
                # Сохраняем информацию об ордере
                self.assets_data[symbol]['active_order'] = {
                    'id': order_id,
                    'timestamp': time.time(),
                    'price': price,
                    'side': side,
                    'qty': qty
                }
                return order_id
            else:
                logger.error(f"[{symbol}] Ошибка размещения ордера {side}: {order}")
                return ""
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка размещения ордера {side}: {e}")
            return ""
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Отменить ордер"""
        try:
            logger.info(f"[{symbol}] Отмена ордера {order_id}")
            response = self.session.cancel_order(
                category="linear",
                symbol=symbol,
                orderId=order_id
            )
            logger.info(f"[{symbol}] Ордер {order_id} отменен")
            # Очищаем информацию об активном ордере
            self.assets_data[symbol]['active_order'] = None
            return True
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка отмены ордера {order_id}: {e}")
            return False
    def trade_asset(self, symbol: str):
        """Торговля одним активом"""
        if not self.trading_active:
            return
        # Проверяем, включен ли актив для торговли
        if not self.assets_config.get(symbol, {}).get('enabled', False):
            logger.info(f"[{symbol}] Отключен для торговли")
            return
        try:
            # Получаем конфигурацию актива
            config = self.assets_config.get(symbol)
            if not config:
                logger.warning(f"[{symbol}] Нет конфигурации")
                return
            # Получаем текущую цену
            current_price = self.get_asset_price(symbol)
            if current_price <= 0:
                logger.warning(f"[{symbol}] Невозможно получить цену")
                return
            self.assets_data[symbol]['last_price'] = current_price
            # Получаем позицию
            position_data = self.get_asset_position(symbol)
            self.assets_data[symbol]['position'] = position_data['position']
            self.assets_data[symbol]['avg_price'] = position_data['avg_price']
            # Сохраняем PNL из полученных данных позиции
            self.assets_data[symbol]['daily_pnl'] = position_data.get('pnl', 0)
            self.assets_data[symbol]['weekly_pnl'] = position_data.get('pnl', 0)
            self.assets_data[symbol]['position_side'] = position_data['side']
            # Устанавливаем цену отсчета если еще не установлена
            if self.assets_data[symbol]['reference_price'] == 0:
                self.assets_data[symbol]['reference_price'] = current_price
                logger.info(f"[{symbol}] Цена отсчета установлена: {current_price}")
            # Рассчитываем уровни покупки и продажи
            buy_price_level = self.assets_data[symbol]['reference_price'] * (1 - config['k_percent'] / 100)
            sell_price_level = self.assets_data[symbol]['avg_price'] * (1 + config['n_percent'] / 100) if self.assets_data[symbol]['avg_price'] > 0 else 0
            self.assets_data[symbol]['buy_price_level'] = round(buy_price_level, 4)
            self.assets_data[symbol]['sell_price_level'] = round(sell_price_level, 4)
            # Обновляем цену отсчета раз в 24 часа
            if time.time() - self.assets_data[symbol]['last_update'] > 24 * 3600:
                self.assets_data[symbol]['reference_price'] = current_price
                self.assets_data[symbol]['last_update'] = time.time()
                logger.info(f"[{symbol}] Цена отсчета обновлена: {current_price}")
            # Проверяем активный ордер
            if self.assets_data[symbol]['active_order']:
                if time.time() - self.assets_data[symbol]['active_order']['timestamp'] > self.order_ttl:
                    # Отменяем просроченный ордер
                    self.cancel_order(symbol, self.assets_data[symbol]['active_order']['id'])
                    logger.info(f"[{symbol}] Ордер отменен по истечении TTL")
                else:
                    logger.info(f"[{symbol}] Активный ордер ожидает исполнения")
                    return
            # Условия для покупки (30% от позиции, но не менее минимального лота)
            buy_condition = (
                    (self.assets_data[symbol]['position'] <= 0 or
                     (self.assets_data[symbol]['avg_price'] > 0 and
                      current_price < self.assets_data[symbol]['avg_price'] * (1 - config['k_percent'] / 100))) and
                    current_price < buy_price_level
            )
            # Условия для продажи (уменьшение позиции на 35%)
            sell_condition = (
                    self.assets_data[symbol]['position'] > 0 and
                    self.assets_data[symbol]['avg_price'] > 0 and
                    current_price > sell_price_level
            )
            # Покупка (30% от позиции, но не менее минимального лота)
            if buy_condition and abs(self.assets_data[symbol]['position']) <= config['max_position'] - self.assets_data[symbol]['min_lot']:
                # Рассчитываем размер лота (30% от позиции)
                position_size = abs(self.assets_data[symbol]['position'])
                lot_size = position_size * (self.buy_percent / 100)
                # Проверяем минимальный размер
                min_lot = self.assets_data[symbol]['min_lot']
                if lot_size < min_lot:
                    lot_size = min_lot
                # Рассчитываем цену с отступом
                order_price = current_price * (1 - self.price_offset / 100)
                # Размещаем ордер
                order_id = self.place_limit_order(symbol, "Buy", lot_size, order_price)
                if order_id:
                    logger.info(f"[{symbol}] Ордер на покупку размещен: {round(lot_size, 1)} по цене {round(order_price, 4)}")
            # Продажа (уменьшение позиции на 35%)
            elif sell_condition and abs(self.assets_data[symbol]['position']) >= self.assets_data[symbol]['min_lot']:
                # Рассчитываем размер лота (35% от позиции)
                position_size = abs(self.assets_data[symbol]['position'])
                lot_size = position_size * (self.sell_percent / 100)
                # Проверяем минимальный размер
                min_lot = self.assets_data[symbol]['min_lot']
                if lot_size < min_lot:
                    lot_size = min_lot
                # Если осталось мало - продаем всё
                if position_size - lot_size < min_lot:
                    lot_size = position_size
                # Рассчитываем цену с отступом
                order_price = current_price * (1 + self.price_offset / 100)
                # Размещаем ордер на уменьшение позиции
                order_id = self.place_limit_order(symbol, "Sell", lot_size, order_price)
                if order_id:
                    logger.info(f"[{symbol}] Ордер на продажу размещен: {round(lot_size, 1)} по цене {round(order_price, 4)}")
        except Exception as e:
            logger.error(f"[{symbol}] Ошибка торговли: {e}")
            self.assets_data[symbol]['error_message'] = str(e)
    async def run_trading_cycle(self):
        """Запуск торгового цикла"""
        logger.info("Запуск торгового бота для множества активов")
        # Инициализируем лоты для всех активов
        self.initialize_asset_lots()
        while True:
            try:
                if not self.trading_active:
                    logger.info("Торговля остановлена, ожидание...")
                    await asyncio.sleep(30)
                    continue
                logger.info("Выполнение торгового цикла")
                # Обновляем баланс счета
                self.get_account_balance()
                # Торгуем каждым активом
                for symbol in self.assets_config.keys():
                    if self.assets_config[symbol].get('enabled', False):
                        logger.info(f"[{symbol}] Торговля")
                        self.trade_asset(symbol)
                    await asyncio.sleep(1)  # Пауза между активами
                logger.info("Торговый цикл завершен")
                await asyncio.sleep(60)  # Пауза между циклами
            except Exception as e:
                logger.error(f"Критическая ошибка в основном цикле: {e}")
                await asyncio.sleep(60)
    def start_trading(self):
        """Запустить торговлю"""
        self.trading_active = True
        logger.info("Торговля запущена")
    def stop_trading(self):
        """Остановить торговлю"""
        self.trading_active = False
        logger.info("Торговля остановлена")
    def update_asset_config(self, symbol: str, config: Dict[str, Any]):
        """Обновить конфигурацию актива"""
        if symbol in self.assets_config:
            self.assets_config[symbol].update(config)
            logger.info(f"[{symbol}] Конфигурация обновлена: {config}")
            return True
        return False
    def get_status(self) -> Dict[str, Any]:
        """Получить статус всех активов"""
        status = {
            'trading_active': self.trading_active,
            'assets': {},
            'timestamp': time.time(),
            'buy_percent': self.buy_percent,
            'sell_percent': self.sell_percent,
            'price_offset': self.price_offset,
            'min_lot_usd': self.min_lot_usd,
            'account_balance': round(self.account_balance, 2),
            'account_equity': round(self.account_equity, 2),
            'account_available_margin': round(self.account_available_margin, 2),
            'trade_history': list(self.trade_history)[-20:]  # Последние 20 сделок
        }
        for symbol, data in self.assets_data.items():
            config = self.assets_config.get(symbol, {})
            status['assets'][symbol] = {
                'last_price': round(data['last_price'], 2) if data['last_price'] > 0 else 0,
                'position': round(data['position'], 2) if data['position'] != 0 else 0,
                'avg_price': round(data['avg_price'], 2) if data['avg_price'] > 0 else 0,
                'reference_price': round(data['reference_price'], 2) if data['reference_price'] > 0 else 0,
                'active_order': data['active_order'],
                'last_update': data['last_update'],
                'error_message': data['error_message'],
                'min_lot': round(data['min_lot'], 2) if data['min_lot'] > 0 else 0,
                'max_lot': round(data['max_lot'], 2) if data['max_lot'] > 0 else 0,
                'lot_size_step': data['lot_size_step'],
                'buy_price_level': round(data['buy_price_level'], 2) if data['buy_price_level'] > 0 else 0,
                'sell_price_level': round(data['sell_price_level'], 2) if data['sell_price_level'] > 0 else 0,
                'enabled': config.get('enabled', True),
                'n_percent': config.get('n_percent', 5),
                'k_percent': config.get('k_percent', 5),
                'max_position': config.get('max_position', 2.0),
                'daily_pnl': round(data['daily_pnl'], 2),
                'weekly_pnl': round(data['weekly_pnl'], 2)
            }
        return status
# Создаем экземпляр бота
bot = MultiAssetTradingBot()
# FastAPI приложение
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
app = FastAPI(title="Multi-Asset Trading Bot")
# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
html = """
<!DOCTYPE html>
<html>
<head>
    <title>Multi-Asset Trading Bot</title>
    <meta charset="utf-8">
    <style>
        body { 
            font-family: Arial, sans-serif; 
            margin: 0;
            padding: 20px; 
            background: #f0f2f5; 
            color: #333;
        }
        .container { 
            max-width: 1400px; 
            margin: 0 auto; 
        }
        .header { 
            background: linear-gradient(135deg, #667eea, #764ba2); 
            color: white; 
            padding: 20px; 
            border-radius: 10px; 
            text-align: center; 
            margin-bottom: 20px; 
        }
        .account-info {
            display: flex;
            justify-content: space-around;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .account-item {
            text-align: center;
        }
        .account-label {
            font-size: 0.9rem;
            color: #6c757d;
        }
        .account-value {
            font-size: 1.2rem;
            font-weight: bold;
            color: #28a745;
        }
        .controls { 
            display: flex; 
            gap: 10px; 
            justify-content: center; 
            margin-bottom: 20px; 
            flex-wrap: wrap; 
        }
        .btn { 
            padding: 12px 24px; 
            border: none; 
            border-radius: 6px; 
            cursor: pointer; 
            font-weight: bold; 
            transition: all 0.3s; 
        }
        .btn-start { 
            background: #28a745; 
            color: white; 
        }
        .btn-stop { 
            background: #dc3545; 
            color: white; 
        }
        .btn-admin { 
            background: #6c757d; 
            color: white; 
        }
        .status-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); 
            gap: 20px; 
            margin-bottom: 20px; 
        }
        .card { 
            background: white; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1); 
        }
        .card-header { 
            font-size: 1.2rem; 
            font-weight: bold; 
            margin-bottom: 15px; 
            color: #333; 
            border-bottom: 2px solid #e9ecef; 
            padding-bottom: 10px; 
        }
        .metrics { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 15px; 
        }
        .metric { 
            text-align: center; 
            padding: 15px; 
            background: #f8f9fa; 
            border-radius: 6px; 
        }
        .metric-value { 
            font-size: 1.1rem; 
            font-weight: bold; 
            margin: 8px 0; 
        }
        .position-long { 
            color: #28a745; 
        }
        .position-short { 
            color: #dc3545; 
        }
        .position-neutral { 
            color: #6c757d; 
        }
        .error { 
            background: #f8d7da; 
            color: #721c24; 
            padding: 15px; 
            border-radius: 6px; 
            margin: 20px 0; 
        }
        .success { 
            background: #d4edda; 
            color: #155724; 
            padding: 15px; 
            border-radius: 6px; 
            margin: 20px 0; 
        }
        .warning { 
            background: #fff3cd; 
            color: #856404; 
            padding: 15px; 
            border-radius: 6px; 
            margin: 20px 0; 
        }
        .signal-positive { 
            color: #28a745; 
            font-weight: bold; 
        }
        .signal-negative { 
            color: #dc3545; 
            font-weight: bold; 
        }
        .signal-neutral { 
            color: #6c757d; 
            font-weight: bold; 
        }
        .trades { 
            max-height: 300px; 
            overflow-y: auto; 
        }
        .trade-item { 
            padding: 8px; 
            margin: 5px 0; 
            border-radius: 4px; 
            background: #f8f9fa; 
            display: flex; 
            justify-content: space-between; 
            font-size: 0.9rem; 
        }
        .trade-buy { 
            border-left: 4px solid #28a745; 
        }
        .trade-sell { 
            border-left: 4px solid #dc3545; 
        }
        .trade-order { 
            border-left: 4px solid #007bff; 
        }
        #status { 
            background: white; 
            padding: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1); 
            margin-top: 20px; 
        }
        .debug-info {
            background: #e9ecef;
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
            font-size: 0.8rem;
        }
        .chart-container {
            height: 500px;
            margin-top: 20px;
        }
        .condition-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-top: 15px;
        }
        .condition-section {
            padding: 15px;
            border-radius: 6px;
            background: #f8f9fa;
        }
        .condition-section.buy {
            border-left: 4px solid #28a745;
        }
        .condition-section.sell {
            border-left: 4px solid #dc3545;
        }
        .condition-detail {
            margin: 8px 0;
            padding: 8px;
            background: white;
            border-radius: 4px;
            display: flex;
            justify-content: space-between;
        }
        .condition-ok {
            color: #28a745;
        }
        .condition-fail {
            color: #dc3545;
        }
        .condition-pending {
            color: #ffc107;
        }
        /* Модальное окно админки */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        .modal-content {
            background-color: white;
            margin: 5% auto;
            padding: 20px;
            border-radius: 10px;
            width: 80%;
            max-width: 1200px;
            max-height: 80vh;
            overflow-y: auto;
        }
        .close {
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover {
            color: black;
        }
        .config-form {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }
        .form-group input, .form-group select {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        .form-actions {
            grid-column: 1 / -1;
            text-align: center;
            margin-top: 20px;
        }
        .btn-save {
            background: #007bff;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
        }
        .btn-save:hover {
            background: #0056b3;
        }
        .password-modal {
            display: none;
            position: fixed;
            z-index: 1001;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        .password-content {
            background-color: white;
            margin: 15% auto;
            padding: 20px;
            border-radius: 10px;
            width: 300px;
            text-align: center;
        }
        .password-content input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        .password-content button {
            padding: 10px 20px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .asset-config-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            margin: 5px 0;
            background: #f8f9fa;
            border-radius: 4px;
        }
        .asset-config-controls {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .asset-config-input {
            width: 60px;
            padding: 5px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        .btn-toggle {
            padding: 5px 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .btn-toggle.enabled {
            background: #28a745;
            color: white;
        }
        .btn-toggle.disabled {
            background: #dc3545;
            color: white;
        }
        .min-lot-display {
            font-size: 0.8rem;
            color: #6c757d;
            margin-left: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Multi-Asset Trading Bot - Bybit</h1>
            <p>Автоматическая торговля множеством фьючерсов</p>
        </div>
        <div class="account-info">
            <div class="account-item">
                <div class="account-label">Баланс USDT</div>
                <div class="account-value" id="accountBalance">$0.00</div>
            </div>
            <div class="account-item">
                <div class="account-label">Эквити</div>
                <div class="account-value" id="accountEquity">$0.00</div>
            </div>
            <div class="account-item">
                <div class="account-label">Доступная маржа</div>
                <div class="account-value" id="availableMargin">$0.00</div>
            </div>
        </div>
        <div class="controls">
            <button class="btn btn-start" onclick="startTradingWithPassword()">ЗАПУСТИТЬ ТОРГОВЛЮ</button>
            <button class="btn btn-stop" onclick="stopTradingWithPassword()">ОСТАНОВИТЬ ТОРГОВЛЮ</button>
            <button class="btn btn-admin" onclick="showPasswordModal()">АДМИН ПАНЕЛЬ</button>
            <button class="btn" style="background: #007bff; color: white;" onclick="refreshData()">ОБНОВИТЬ ДАННЫЕ</button>
        </div>
        <div id="status">
            <div class="warning">Ожидание подключения WebSocket...</div>
        </div>
    </div>
    <!-- Модальное окно пароля -->
    <div id="passwordModal" class="password-modal">
        <div class="password-content">
            <h3>Введите пароль администратора</h3>
            <input type="password" id="adminPassword" placeholder="Пароль">
            <br>
            <button onclick="checkPassword()">Войти</button>
            <button onclick="closePasswordModal()" style="background: #6c757d; margin-left: 10px;">Отмена</button>
        </div>
    </div>
    <!-- Модальное окно админки -->
    <div id="adminModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeAdminPanel()">&times;</span>
            <h2>Административная панель</h2>
            <div class="config-form">
                <div class="form-group">
                    <label for="buyPercent">Процент покупки (%):</label>
                    <input type="number" id="buyPercent" step="1" min="1" max="100" value="30">
                </div>
                <div class="form-group">
                    <label for="sellPercent">Процент продажи (%):</label>
                    <input type="number" id="sellPercent" step="1" min="1" max="100" value="35">
                </div>
                <div class="form-group">
                    <label for="priceOffset">Отступ цены (%):</label>
                    <input type="number" id="priceOffset" step="0.1" min="0.1" max="5" value="0.3">
                </div>
                <div class="form-group">
                    <label for="minLotUsd">Минимальный лот ($):</label>
                    <input type="number" id="minLotUsd" step="1" min="1" max="100" value="5">
                </div>
                <div class="form-group" style="grid-column: 1 / -1;">
                    <h3>Конфигурация активов</h3>
                    <div id="assetsConfig">
                        <!-- Здесь будут динамически добавлены настройки активов -->
                    </div>
                </div>
                <div class="form-actions">
                    <button class="btn-save" onclick="saveGlobalConfig()">СОХРАНИТЬ ОБЩИЕ НАСТРОЙКИ</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        let ws = null;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 10;
        let chart = null;
        function connectWebSocket() {
            const wsUrl = `ws://${window.location.host}/ws`;
            console.log('Попытка подключения к WebSocket:', wsUrl);
            ws = new WebSocket(wsUrl);
            ws.onopen = function(event) {
                console.log('WebSocket подключен');
                reconnectAttempts = 0;
                document.getElementById('status').innerHTML = `
                    <div class="success">WebSocket подключен. Ожидание данных...</div>
                `;
            };
            ws.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    console.log('Получены данные:', data);
                    renderStatus(data);
                } catch (error) {
                    console.error('Ошибка обработки данных:', error);
                    document.getElementById('status').innerHTML = `
                        <div class="error">Ошибка обработки данных: ${error.message}</div>
                    `;
                }
            };
            ws.onclose = function(event) {
                console.log('WebSocket отключен');
                document.getElementById('status').innerHTML = `
                    <div class="warning">WebSocket отключен. Попытка переподключения...</div>
                `;
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    setTimeout(connectWebSocket, 3000);
                } else {
                    document.getElementById('status').innerHTML = `
                        <div class="error">Не удалось подключиться к WebSocket после ${maxReconnectAttempts} попыток</div>
                    `;
                }
            };
            ws.onerror = function(error) {
                console.error('Ошибка WebSocket:', error);
                document.getElementById('status').innerHTML = `
                    <div class="error">Ошибка WebSocket: ${error.message}</div>
                `;
            };
        }
        function startTradingWithPassword() {
            showPasswordModalForAction('start');
        }
        function stopTradingWithPassword() {
            showPasswordModalForAction('stop');
        }
        function showPasswordModalForAction(action) {
            window.pendingAction = action;
            document.getElementById('passwordModal').style.display = 'block';
            document.getElementById('adminPassword').focus();
        }
        function executePendingAction(password) {
            if (window.pendingAction === 'start') {
                startTrading(password);
            } else if (window.pendingAction === 'stop') {
                stopTrading(password);
            }
            closePasswordModal();
        }
        function startTrading(password) {
            fetch('/api/start', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({password: password})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Торговля запущена:', data);
                    alert(data.message);
                } else {
                    alert('Ошибка: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Ошибка запуска торговли:', error);
                alert('Ошибка: ' + error.message);
            });
        }
        function stopTrading(password) {
            fetch('/api/stop', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({password: password})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('Торговля остановлена:', data);
                    alert(data.message);
                } else {
                    alert('Ошибка: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Ошибка остановки торговли:', error);
                alert('Ошибка: ' + error.message);
            });
        }
        function refreshData() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    console.log('Обновленные данные:', data);
                    renderStatus(data);
                })
                .catch(error => {
                    console.error('Ошибка обновления данных:', error);
                    document.getElementById('status').innerHTML = `
                        <div class="error">Ошибка обновления данных: ${error.message}</div>
                    `;
                });
        }
        function showPasswordModal() {
            document.getElementById('passwordModal').style.display = 'block';
            document.getElementById('adminPassword').focus();
        }
        function closePasswordModal() {
            document.getElementById('passwordModal').style.display = 'none';
            document.getElementById('adminPassword').value = '';
            window.pendingAction = null;
        }
        function checkPassword() {
            const password = document.getElementById('adminPassword').value;
            if (window.pendingAction) {
                executePendingAction(password);
            } else {
                fetch('/api/check-password', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({password: password})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        closePasswordModal();
                        openAdminPanel();
                    } else {
                        alert('Неверный пароль!');
                    }
                })
                .catch(error => {
                    console.error('Ошибка проверки пароля:', error);
                    alert('Ошибка проверки пароля: ' + error.message);
                });
            }
        }
        // Обработка Enter в поле пароля
        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('adminPassword').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    checkPassword();
                }
            });
        });
        function openAdminPanel() {
            // Загружаем текущие настройки
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    // Заполняем общие настройки
                    document.getElementById('buyPercent').value = data.buy_percent || 30;
                    document.getElementById('sellPercent').value = data.sell_percent || 35;
                    document.getElementById('priceOffset').value = data.price_offset || 0.3;
                    document.getElementById('minLotUsd').value = data.min_lot_usd || 5;
                    // Заполняем настройки активов
                    const assetsConfigDiv = document.getElementById('assetsConfig');
                    let assetsHtml = '';
                    for (const [symbol, assetData] of Object.entries(data.assets || {})) {
                        const config = data.assets_config ? data.assets_config[symbol] : {};
                        const minLotUsd = assetData.min_lot && assetData.last_price ? (assetData.min_lot * assetData.last_price).toFixed(2) : '0.00';
                        assetsHtml += `
                            <div class="asset-config-row" id="config-${symbol}">
                                <div><strong>${symbol}</strong></div>
                                <div class="asset-config-controls">
                                    <input type="number" class="asset-config-input" id="n_${symbol}" value="${config.n_percent || 5}" min="1" max="50" placeholder="n%">
                                    <input type="number" class="asset-config-input" id="k_${symbol}" value="${config.k_percent || 5}" min="1" max="50" placeholder="k%">
                                    <input type="number" class="asset-config-input" id="max_${symbol}" value="${config.max_position || 2}" min="0.1" max="10" step="0.1" placeholder="max">
                                    <button class="btn-toggle ${config.enabled ? 'enabled' : 'disabled'}" 
                                            onclick="toggleAsset('${symbol}')" 
                                            id="toggle_${symbol}">
                                        ${config.enabled ? 'Вкл' : 'Выкл'}
                                    </button>
                                    <span class="min-lot-display">${minLotUsd}$</span>
                                    <button class="btn-save" onclick="saveAssetConfig('${symbol}')" style="padding: 5px 10px; font-size: 0.8rem;">💾</button>
                                </div>
                            </div>
                        `;
                    }
                    assetsConfigDiv.innerHTML = assetsHtml;
                    document.getElementById('adminModal').style.display = 'block';
                })
                .catch(error => {
                    console.error('Ошибка загрузки настроек:', error);
                    alert('Ошибка загрузки настроек: ' + error.message);
                });
        }
        function closeAdminPanel() {
            document.getElementById('adminModal').style.display = 'none';
        }
        function toggleAsset(symbol) {
            const button = document.getElementById(`toggle_${symbol}`);
            const isEnabled = button.classList.contains('enabled');
            // Обновляем визуальное состояние
            if (isEnabled) {
                button.classList.remove('enabled');
                button.classList.add('disabled');
                button.textContent = 'Выкл';
            } else {
                button.classList.remove('disabled');
                button.classList.add('enabled');
                button.textContent = 'Вкл';
            }
            // Отправляем обновление на сервер
            fetch('/api/asset-config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    symbol: symbol,
                    enabled: !isEnabled
                })
            })
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    alert('Ошибка обновления: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Ошибка обновления актива:', error);
                alert('Ошибка обновления актива: ' + error.message);
            });
        }
       function saveAssetConfig(symbol) {
    const config = {
        symbol: symbol,
        n_percent: parseFloat(document.getElementById(`n_${symbol}`).value),
        k_percent: parseFloat(document.getElementById(`k_${symbol}`).value),
        max_position: parseFloat(document.getElementById(`max_${symbol}`).value)
    };
    fetch('/api/asset-config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`Настройки ${symbol} сохранены!`);
            refreshData();
        } else {
            alert('Ошибка сохранения: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Ошибка сохранения настроек:', error);
        alert('Ошибка сохранения: ' + error.message);
    });
}
        function saveGlobalConfig() {
            const config = {
                buy_percent: parseInt(document.getElementById('buyPercent').value),
                sell_percent: parseInt(document.getElementById('sellPercent').value),
                price_offset: parseFloat(document.getElementById('priceOffset').value),
                min_lot_usd: parseFloat(document.getElementById('minLotUsd').value)
            };
            fetch('/api/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(config)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Общие настройки сохранены!');
                    closeAdminPanel();
                    refreshData();
                } else {
                    alert('Ошибка сохранения: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Ошибка сохранения настроек:', error);
                alert('Ошибка сохранения: ' + error.message);
            });
        }
        function renderStatus(data) {
            try {
                // Обновляем баланс счета
                if (data.account_balance !== undefined) {
                    document.getElementById('accountBalance').textContent = `$${data.account_balance.toFixed(2)}`;
                    document.getElementById('accountEquity').textContent = `$${data.account_equity.toFixed(2)}`;
                    document.getElementById('availableMargin').textContent = `$${data.account_available_margin.toFixed(2)}`;
                }
                const updateTime = data.timestamp ? new Date(data.timestamp * 1000).toLocaleString('ru-RU') : 'Неизвестно';
                let statusHtml = `
                    <div class="debug-info">
                        Debug: Получены данные в ${new Date().toLocaleTimeString('ru-RU')}
                    </div>
                `;
                if (data.error_message) {
                    statusHtml += `<div class="error"><strong>Ошибка:</strong> ${data.error_message}</div>`;
                }
                statusHtml += data.trading_active ? 
                    `<div class="success">Торговля АКТИВНА</div>` : 
                    `<div class="warning">Торговля ОСТАНОВЛЕНА</div>`;
                statusHtml += `
                <div class="status-grid">
                `;
                // Создаем карточки для каждого актива
                for (const [symbol, assetData] of Object.entries(data.assets || {})) {
                    const config = data.assets_config ? data.assets_config[symbol] : {};
                    const isEnabled = assetData.enabled !== undefined ? assetData.enabled : true;
                    statusHtml += `
                    <div class="card">
                        <div class="card-header">${symbol} ${isEnabled ? '✅' : '❌'}</div>
                        <div class="metrics">
                            <div class="metric">
                                <div>Текущая цена</div>
                                <div class="metric-value">${assetData.last_price ? '$' + assetData.last_price.toFixed(2) : '$0.00'}</div>
                            </div>
                            <div class="metric">
                                <div>Позиция</div>
                                <div class="metric-value ${getPositionClass(assetData.position)}">
                                    ${formatPosition(assetData.position)} @ ${assetData.avg_price ? '$' + assetData.avg_price.toFixed(2) : 'N/A'}
                                </div>
                            </div>
                            <div class="metric">
                                <div>Unreal. PNL</div>
                                <div class="metric-value" style="${(parseFloat(assetData.daily_pnl) || 0) >= 0 ? 'color: #28a745;' : 'color: #dc3545;'}">
                                    ${(parseFloat(assetData.daily_pnl) || 0).toFixed(2)} USDT
                                </div>
                            </div>
                            <div class="metric">
                                <div>Цена отсчета</div>
                                <div class="metric-value">${assetData.reference_price ? '$' + assetData.reference_price.toFixed(2) : '$0.00'}</div>
                            </div>
                            <div class="metric">
                                <div>Активный ордер</div>
                                <div class="metric-value">${assetData.active_order ? '✅ Да' : '❌ Нет'}</div>
                            </div>
                            <div class="metric">
                                <div>Уровень покупки</div>
                                <div class="metric-value">${assetData.buy_price_level ? '$' + assetData.buy_price_level.toFixed(2) : '$0.00'}</div>
                            </div>
                            <div class="metric">
                                <div>Уровень продажи</div>
                                <div class="metric-value">${assetData.sell_price_level ? '$' + assetData.sell_price_level.toFixed(2) : '$0.00'}</div>
                            </div>
                            <div class="metric">
                                <div>Мин. лот</div>
                                <div class="metric-value">${assetData.min_lot ? assetData.min_lot.toFixed(2) : '0.00'}</div>
                            </div>
                            <div class="metric">
                                <div>Макс. лот</div>
                                <div class="metric-value">${assetData.max_lot ? assetData.max_lot.toFixed(2) : '0.00'}</div>
                            </div>
                        </div>
                    </div>
                    `;
                }
                statusHtml += `
                </div>
                <div style="text-align: center; color: #6c757d; font-size: 0.9rem; margin-top: 10px;">
                    Последнее обновление: ${updateTime}
                </div>
                `;
                document.getElementById('status').innerHTML = statusHtml;
            } catch (error) {
                console.error('Ошибка рендеринга:', error);
                document.getElementById('status').innerHTML = `
                    <div class="error">Ошибка рендеринга: ${error.message}</div>
                `;
            }
        }
        function getPositionClass(position) {
            const pos = parseFloat(position) || 0;
            if (pos > 0) return 'position-long';
            if (pos < 0) return 'position-short';
            return 'position-neutral';
        }
        function formatPosition(position) {
            const pos = parseFloat(position) || 0;
            if (pos > 0) return '🟢 LONG ' + Math.abs(pos).toFixed(2);
            if (pos < 0) return '🔴 SHORT ' + Math.abs(pos).toFixed(2);
            return '⚪ Нет позиции';
        }
        // Закрытие модального окна при клике вне его
        window.onclick = function(event) {
            const passwordModal = document.getElementById('passwordModal');
            const adminModal = document.getElementById('adminModal');
            if (event.target == passwordModal) {
                closePasswordModal();
            }
            if (event.target == adminModal) {
                closeAdminPanel();
            }
        }
        // Инициализация
        connectWebSocket();
    </script>
</body>
</html>
"""
@app.get("/")
async def get():
    return HTMLResponse(html)
@app.get("/api/status")
async def get_status():
    """Получить текущий статус через REST API"""
    status = bot.get_status()
    return status
@app.post("/api/start")
async def start_trading(data: PasswordCheck):
    """Запустить торговлю с проверкой пароля"""
    if data.password == bot.admin_password:
        bot.start_trading()
        return {"success": True, "message": "Торговля запущена"}
    else:
        return {"success": False, "message": "Неверный пароль"}
@app.post("/api/stop")
async def stop_trading(data: PasswordCheck):
    """Остановить торговлю с проверкой пароля"""
    if data.password == bot.admin_password:
        bot.stop_trading()
        return {"success": True, "message": "Торговля остановлена"}
    else:
        return {"success": False, "message": "Неверный пароль"}
@app.post("/api/config")
async def update_config(config: ConfigUpdate):
    """Обновить конфигурацию"""
    try:
        # Обновляем общие настройки
        if config.buy_percent is not None:
            bot.buy_percent = config.buy_percent
        if config.sell_percent is not None:
            bot.sell_percent = config.sell_percent
        if config.price_offset is not None:
            bot.price_offset = config.price_offset
        if config.min_lot_usd is not None:
            bot.min_lot_usd = config.min_lot_usd
        logger.info("Конфигурация обновлена")
        return {"success": True, "message": "Конфигурация обновлена"}
    except Exception as e:
        logger.error(f"Ошибка обновления конфигурации: {e}")
        return {"success": False, "error": str(e)}
@app.post("/api/asset-config")
async def update_asset_config(config: AssetConfigUpdate):
    """Обновить конфигурацию актива"""
    try:
        symbol = config.symbol
        if not symbol:
            return {"success": False, "error": "Не указан символ"}
        # Обновляем конфигурацию
        asset_config = bot.assets_config.get(symbol, {})
        if config.enabled is not None:
            asset_config['enabled'] = config.enabled
        if config.n_percent is not None:
            asset_config['n_percent'] = config.n_percent
        if config.k_percent is not None:
            asset_config['k_percent'] = config.k_percent
        if config.max_position is not None:
            asset_config['max_position'] = config.max_position
        bot.assets_config[symbol] = asset_config
        logger.info(f"[{symbol}] Конфигурация обновлена: {config.dict()}")
        return {"success": True}
    except Exception as e:
        logger.error(f"[{config.symbol}] Ошибка обновления конфигурации: {e}")
        return {"success": False, "error": str(e)}
@app.post("/api/check-password")
async def check_password(data: PasswordCheck):
    """Проверить пароль администратора"""
    if data.password == bot.admin_password:
        return {"success": True}
    else:
        return {"success": False}
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint для реал-тайм обновлений"""
    await websocket.accept()
    bot.websocket_listeners.add(websocket)
    try:
        # Отправляем начальный статус
        status = bot.get_status()
        await websocket.send_json(status)
        print("Отправлены начальные данные клиенту")
        # Держим соединение открытым
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("Клиент WebSocket отключен")
        bot.websocket_listeners.discard(websocket)
    except Exception as e:
        print(f"Ошибка WebSocket: {e}")
        bot.websocket_listeners.discard(websocket)
# Запуск торгового цикла в фоне
@app.on_event("startup")
async def startup_event():
    """Запуск торгового цикла при старте приложения"""
    print("Запуск торгового цикла...")
    # Запускаем торговый цикл в фоновом режиме
    asyncio.create_task(bot.run_trading_cycle())
if __name__ == "__main__":
    print("MULTI-ASSET TRADING BOT - BYBIT")
    print("=" * 50)
    print("Поддерживаемые активы:")
    for symbol, config in bot.assets_config.items():
        print(f"  {symbol}: n-{config['n_percent']}% k-{config['k_percent']}% max_pos={config['max_position']} {'✅' if config['enabled'] else '❌'}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)



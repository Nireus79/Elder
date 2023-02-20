from pykrakenapi import KrakenAPI
import krakenex
from datetime import datetime
import requests
import urllib.parse
import hashlib
import hmac
import base64
from ta.momentum import stoch, rsi
from ta.volatility import average_true_range
import os
import time
import pandas as pd

api_url = "https://api.kraken.com"
api_key = os.environ['API_KEY_KRAKEN']
api_sec = os.environ['API_SEC_KRAKEN']
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)


def get_kraken_signature(url, data, secret):
    post_data = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + post_data).encode()
    message = url.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sig_digest = base64.b64encode(mac.digest())
    return sig_digest.decode()


def kraken_request(uri_path, data, key, sec):
    headers = {'API-Key': key, 'API-Sign': get_kraken_signature(uri_path, data, sec)}
    req = requests.post((api_url + uri_path), headers=headers, data=data)
    return req


def get_private_balance():
    resp = kraken_request('/0/private/Balance', {
        "nonce": str(int(1000 * time.time()))
    }, api_key, api_sec)
    return resp.json()


def get_condition(crypto_currency, fiat_currency, closing_price):
    """
    Takes the private user's account balance and gives condition to buy or sell to the bot.
    If balance has less crypto value than fiat returns condition "buy"
    for the bot to look for good crypto buy conditions.
    If balance has more crypto value than fiat returns condition "sell"
    for the bot to look for good crypto sell conditions.
    :return: Conditions to buy/sell crypto.
    """
    fiat_currency = 'Z' + fiat_currency
    balance = get_private_balance()
    crypto_balance = float(balance['result'][crypto_currency])
    crypto_value = crypto_balance * closing_price
    fiat_balance = float(balance['result'][fiat_currency])
    if crypto_value < fiat_balance:
        return 'buy', crypto_balance, fiat_balance
    elif crypto_value >= fiat_balance:
        return 'sell', crypto_balance, fiat_balance
    else:
        log = 'No balance found. Please select existing assets in your account.'
        print(log)


def add_order(ordertype, cond, vol, price, crypto_currency, fiat_currency):
    """
    https://support.kraken.com/hc/en-us/articles/360022839631-Open-Orders
    :param crypto_currency:
    :param fiat_currency:
    :param ordertype: market / limit
    :param cond: buy / sell
    :param vol: vol of fiat or crypto
    :param price: order price
    :return: order response
    """
    pair = crypto_currency + fiat_currency
    resp = kraken_request('/0/private/AddOrder', {
        "nonce": str(int(1000 * time.time())),
        "ordertype": ordertype,
        "type": cond,
        "volume": vol,
        "pair": pair,
        "price": price
    }, key=api_key, sec=api_sec)
    return resp.json()


def cancel_order():
    """
    Cancel all orders
    :return:
    """
    resp = kraken_request('/0/private/CancelAll', {
        "nonce": str(int(1000 * time.time()))
    }, api_key, api_sec)
    """
    or cancel specific order (needs txid)
    resp = kraken_request('/0/private/CancelOrder', {
    "nonce": str(int(1000*time.time())),
    "txid": "OG5V2Y-RYKVL-DT3V3B" EXAMPLE!!! (Give txid as argument)
    }, api_key, api_sec)
    """
    return resp.json()


def get_order_info(txid):
    resp = kraken_request('/0/private/QueryOrders', {
        "nonce": str(int(1000 * time.time())),
        "txid": txid,
        "trades": True
    }, api_key, api_sec)
    return resp.json()


def time_stamp(unix):
    """
    Takes unix time and gives datetime format.
    :param unix: unix time.time()
    :return: Readable datetime format.
    """
    ts = int(unix) + 7200  # (7200 +2 hours winter, 10800 +3 hours summer) for local time Athens
    return datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def high_frame_indicators(df):
    """
    Takes a pandas dataframe provided by Kraken rest api containing ohlc data,
    adding columns to each row with the technical indicators of ohlc (EMA13, macd),
    using the "ta" library.
    Then after comparing the indicators of the last df row, is adding columns with triggers and buy/sell flags.
    : param hdf: raw api dataframe
    :return: hdf enriched with technical indicators and flags
    """
    hdf = df.copy()
    hdf['EMA1'] = hdf['close'].rolling(28).mean()
    hdf['trend'] = hdf.apply(lambda x: x['close'] > x['EMA1'], axis=1)
    return hdf


def mid_frame_indicators(df):
    upper_bound = 37
    lower_bound = 11
    rs = 70
    """
    Takes a pandas dataframe provided by Kraken rest api containing ohlc data,
    adding columns to each row with the technical indicators of ohlc (stochastic %k, stochastic%d, rsi, %atr),
    using the "ta" library.
    : param mdf: raw api dataframe
    :return: mdf enriched with technical indicators and flags
    """
    mdf = df.copy()
    mdf['%K'] = stoch(mdf['high'], mdf['low'], mdf['close'], window=14, smooth_window=3, fillna=False)
    mdf['%D'] = mdf['%K'].rolling(3).mean()
    mdf['rsi'] = rsi(mdf['close'], window=14, fillna=False)
    mdf['buy flag'] = mdf.apply(lambda x: x['%K'] > x['%D'] > lower_bound and x['rsi'] < rs, axis=1)
    mdf['sell flag'] = mdf.apply(lambda x: x['%K'] < x['%D'] < upper_bound, axis=1)
    return mdf


def low_frame_indicators(df):
    """
    Takes a pandas dataframe provided by Kraken rest api containing ohlc data,
    adding column to each row with the technical indicators of atr,
    using the "ta" library.
    :param df: low data frame
    :return: ldf enriched with atr
    """
    ldf = df.copy()
    ldf['atr'] = average_true_range(ldf['high'], ldf['low'], ldf['close'], window=14, fillna=False)
    return ldf


def high_data(frame):
    """
        FOR USE IN APEXCHARTS
        Takes a pandas dataframe and creates a tuple of lists with
        the needed values for the apexcharts candle charts.
        Axis X values are all multiplied by 1000.
        JavaScript Date object however uses milliseconds since 1 January 1970 UTC.
        Therefore, you should multiply your timestamps by 1000 prior to assign the data to the chart configuration.
        :param frame: The modified pandas dataframe from high_frame_indicators.
        :return: json and last running indicators to be displayed.
    """
    front_df = frame.fillna(0)
    front_df['time'] = front_df['time'].apply(lambda x: (x * 1000) + 10800000)  # *1000 javascript time + 3hours
    data_list = front_df.values.tolist()
    candle_data = []
    ema_data = []
    for i in data_list:
        candle_data.append({
            'x': i[0],
            'y': [i[1], i[2], i[3], i[4]]
        })
    for i in data_list:
        if i[8] != 0:
            ema_data.append({
                'x': i[0],
                'y': round(i[8], 4)
            })
    return candle_data, ema_data


def mid_data(frame):
    """
    Same as above (high) FOR USE IN APEXCHARTS
    """
    front_df = frame.fillna(0)
    front_df['time'] = front_df['time'].apply(lambda x: (x * 1000) + 10800000)
    data_list = front_df.values.tolist()
    candle_data = []
    stoch_k_data = round(data_list[-1][8], 4)
    stoch_d_data = round(data_list[-1][9], 4)
    rsi_data = round(data_list[-1][10], 4)
    for i in data_list:
        candle_data.append({
            'x': i[0],
            'y': [i[1], i[2], i[3], i[4]]
        })
    return candle_data, stoch_k_data, stoch_d_data, rsi_data


def low_data(frame):
    """
    Same as above (mid) FOR USE IN APEXCHARTS
    """
    front_df = frame.fillna(0)
    front_df['time'] = front_df['time'].apply(lambda x: (x * 1000) + 10800000)
    data_list = front_df.values.tolist()
    candle_data = []
    atr_data = round(data_list[-1][8], 4)
    for i in data_list:
        candle_data.append({
            'x': i[0],
            'y': [i[1], i[2], i[3], i[4]]
        })
    return candle_data, atr_data


class Api:
    """
    crypto: the name of crypto
    fiat: the name of monetary currency
    interval: candle in min
    frame_len: the length of frame (how many candles)
    """

    def __init__(self, crypto, fiat, interval, frame_len):
        self.frame_len = frame_len
        self.crypto = crypto
        self.fiat = fiat
        self.interval = interval  # candle in minutes
        self.pair = self.crypto + self.fiat
        self.candle = interval * 60  # candle in seconds
        self.last_candle = int(time.time()) - self.candle  # 1 candle in seconds
        self.frame = int(time.time()) - self.candle * self.frame_len
        self.key = os.environ['API_KEY_KRAKEN']
        self.sec = os.environ['API_SEC_KRAKEN']

    def get_frame(self):
        api = krakenex.API()
        k = KrakenAPI(api)
        ohlc, last = k.get_ohlc_data(self.pair, interval=self.interval, since=self.frame)
        return ohlc.iloc[::-1]  # reverse rows

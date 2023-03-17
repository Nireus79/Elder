import logging
import time
import threading
import winsound
from app.back.kraken import Api, high_frame_indicators, mid_frame_indicators, low_frame_indicators, time_stamp, \
    add_order, cancel_order, get_condition, high_data, mid_data, low_data
from app.back.spring import check, activation

logging.basicConfig(level=logging.INFO)

condition = None
bot_mode = None
crypto_balance = None
fiat_balance = 0
limit = None
stop = None
pillow = 0
closing_price = None
trend = None
buy_flag = None
sell_flag = None
runningHighFrame = None
runningMidFrame = None
runningLowFrame = None
high_chart_data = None
mid_chart_data = None
low_chart_data = None
high_ema1 = None
mid_k = None
mid_d = None
mid_rsi = None
low_atr = None
low_limit = None
low_stop = None
log = 'Please set control parameters to start.'
logs = []
trades = []

break_event = threading.Event()


def signal_handler():
    """
    Setting exit event to allow process end
    within while loops before program stop.
    """
    break_event.set()


def beeper(cond):
    """
    Triggers sound signal user notifications on important trading events.
    :param cond: sell / buy / start (events)
    """
    if cond == 'buy':
        for _ in range(5):
            winsound.Beep(440, 500)
            time.sleep(0.5)
    elif cond == 'sell':
        for _ in range(5):
            winsound.Beep(1000, 500)
            time.sleep(0.1)
    elif cond == 'start':
        winsound.Beep(440, 2000)
    elif cond == 'break':
        winsound.Beep(240, 2000)


def chart_data(high_frame, mid_frame, low_frame):
    global high_chart_data, high_ema1, mid_chart_data, mid_k, mid_d, mid_rsi, \
        low_chart_data, low_limit, low_stop, low_atr
    limit_data = []
    stop_data = []
    high_candles, high_ema1 = high_data(high_frame)
    mid_candles, mid_k, mid_d, mid_rsi = mid_data(mid_frame)
    low_candles, low_atr = low_data(low_frame)
    for i in low_candles:
        limit_data.append({
            'x': i['x'],
            'y': limit
        })
        stop_data.append({
            'x': i['x'],
            'y': stop
        })
    high_chart_data = high_candles
    mid_chart_data = mid_candles
    low_chart_data = low_candles
    low_limit = limit_data
    low_stop = stop_data


def order_manager(mode, high, mid, low, cond, crypto_currency, fiat_currency):
    """
    When conditions to buy or sell are aligned in higher frames (buy or sell flag True)
    order_manager is setting limit and stop loss levels.
    Then starts monitoring periodically closing price at current running low time frame duration:
        When intending to buy asset
            if mid-frame momentum is strong:
                if closing price exceeds set limit level:
                    places a market buy order for the asset
                else: (closing price under limit)
                    if new closing price is lower than limit:
                        if new higher high of low frame is lower than previous:
                            sets new limit equal to new lower higher high.
                        else:
                            waits one low candle
            else:
                breaks to reevaluate conditions.
        When intending to sell asset
            if mid-frame momentum is weak:
                if closing price is under stop level:
                    places market sell order for the asset.
                else: (closing price over stop-loss)
                    if new closing price is higher than stop-loss:
                        if new lower low of low frame is higher than previous set:
                            sets new stop-loss equal to new higher lower-low.
                        else:
                            waits one low candle
            else:
                breaks to reevaluate conditions.
    :param mode: limit / market
    :param crypto_currency: asset a
    :param fiat_currency: asset b
    :param high: high-frame instance
    :param mid: mid-frame instance
    :param low: low-frame instance
    :param cond: buy / sell
    In stop-loss/limit levels an extra margin of current atr (average true range) is added,
    to include the volatility factor and limit false positioning.
    After setting a buy order, safety "risk" and "reward" levels are stored as safety parameters.
    Risk level = 'low' of mid-frame candle minus low-frame atr.
    Risk = Buy price - Risk level
    Reward = Buy price + (Risk * 2) As 1/2 Risk/Reward ratio.

    WARNING!!!
    When setting market order, volume must be set on the amount of the first asset.
    When setting buy order, vol = (money - money * max kraken fee) / crypto price
    When setting sell order, vol = crypto_balance (fee is calculated by kraken)
    """
    global condition, stop, limit, log, closing_price, runningLowFrame, crypto_balance, fiat_balance, \
        buy_flag, sell_flag, pillow
    beeper('start')
    log = '{} Order management. Setting {}min low frame {} limits.'.format(time_stamp(time.time()), low.interval, cond)
    logging.info(log)
    logs.append(log + '<br>')
    high_f = high_frame_indicators(high.get_frame())
    mid_f = mid_frame_indicators(mid.get_frame())
    low_f = low_frame_indicators(low.get_frame())
    candle_time = low_f.iloc[-1]['time']
    if cond == 'buy':
        limit = low_f.iloc[-1]['high'] + low_f.iloc[-1]['atr']
    elif cond == 'sell':
        stop = low_f.iloc[-1]['low'] - low_f.iloc[-1]['atr']
    closing_price = low_f.iloc[-1]['close']
    log = 'Balance: {} {}. {} {}'.format(crypto_balance, crypto_currency, fiat_balance, fiat_currency)
    logging.info(log)
    logs.append(log + '<br>')
    log = '{} Current price: {}. limit: {}. Stop loss: {}'.format(time_stamp(time.time()), closing_price, limit, stop)
    logging.info(log)
    logs.append(log + '<br>')
    log = '{} Waiting until next {}min candle close.'.format(time_stamp(time.time()), low.interval)
    logging.info(log)
    logs.append(log + '<br>')
    chart_data(high_f, mid_f, low_f)
    time.sleep(60)
    while True:
        low_f = low_frame_indicators(low.get_frame())
        high_f = high_frame_indicators(high.get_frame())
        mid_f = mid_frame_indicators(mid.get_frame())
        buy_flag = mid_f.iloc[-1]['buy flag']
        sell_flag = mid_f.iloc[-1]['sell flag']
        chart_data(high_f, mid_f, low_f)
        new_limit = low_f.iloc[-1]['high'] + low_f.iloc[-1]['atr']
        new_stop = low_f.iloc[-1]['low'] - low_f.iloc[-1]['atr']
        closing_price = low_f.iloc[-1]['close']
        new_candle_time = low_f.iloc[-1]['time']
        if break_event.is_set():  # thread "kill" by user
            cancel_order()
            log = '{} Break ordering.'.format(time_stamp(time.time()))
            logging.info(log)
            logs.append(log + '<br>')
            break
        elif cond == 'buy':
            if buy_flag:
                if new_candle_time > candle_time + low.candle:  # wait one candle to close
                    if closing_price > limit:
                        asset_vol = (fiat_balance - fiat_balance * 0.0026) / closing_price
                        # kraken max trading fee: 0.0026 * asset_vol
                        log = '{} order to {} {} {} using {} {}.' \
                            .format(mode, cond, asset_vol, crypto_currency, fiat_balance, fiat_currency)
                        logging.info(log)
                        tx = add_order(mode, cond, asset_vol, closing_price, crypto_currency, fiat_currency)
                        log = tx
                        logging.info(log)
                        beeper(cond)
                        pillow = closing_price * 0.975
                        log = '{} Bought {} at:.'.format(time_stamp(time.time()), crypto_currency, closing_price)
                        trades.append(log + '<br>')
                        stop = None
                        limit = None
                        break
                    else:
                        candle_time = low_f.iloc[-2]['time']
                        if new_limit < limit:
                            limit = new_limit
                            log = '{} limit set to {}. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), limit, low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                        else:
                            log = '{} Closing price under limit. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                else:
                    time.sleep(60)
            elif buy_flag is not True:
                log = '{} Conditions re-evaluation.'.format(time_stamp(time.time()))
                logging.info(log)
                logs.append(log + '<br>')
                beeper('break')
                time.sleep(10)
                limit = None
                stop = None
                break
        elif cond == 'sell':
            if closing_price < pillow:
                tx = add_order(mode, cond, crypto_balance, closing_price, crypto_currency, fiat_currency)
                log = tx
                logging.info(log)
                beeper(cond)
                log = '{} Sold pillow {} at: {}.'.format(time_stamp(time.time()), crypto_currency, closing_price)
                trades.append(log + '<br>')
                limit = None
                stop = None
                pillow = 0
                break
            elif sell_flag:
                if new_candle_time > candle_time + low.candle:  # wait one candle to close
                    if closing_price < stop:
                        log = '{} order to {} {} {} at {}.' \
                            .format(mode, cond, crypto_balance, crypto_currency, closing_price)
                        logging.info(log)
                        tx = add_order(mode, cond, crypto_balance, closing_price, crypto_currency, fiat_currency)
                        log = tx
                        logging.info(log)
                        beeper(cond)
                        log = '{} Sold {} at: {}.'.format(time_stamp(time.time()), crypto_currency, closing_price)
                        trades.append(log + '<br>')
                        limit = None
                        stop = None
                        pillow = 0
                        break
                    else:
                        candle_time = low_f.iloc[-2]['time']
                        if new_stop > stop:
                            stop = new_stop
                            candle_time = low_f.iloc[-1]['time']
                            log = '{} Stop loss set to {}. Waiting until next{}min  candle close.' \
                                .format(time_stamp(time.time()), stop, low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                        else:
                            log = '{} Closing price over stop. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                else:
                    time.sleep(60)
            elif sell_flag is not True:
                log = '{} Conditions re-evaluation.'.format(time_stamp(time.time()))
                logging.info(log)
                logs.append(log + '<br>')
                beeper('break')
                limit = None
                stop = None
                break


def limit_manager(mode, high, mid, low, cond):
    """
    Same as order_manager.
    No actual order is set.
    User is just informed for the action he has to take.
    :param mode: simulation or consulting
    :param high: The high frame instance, used for chart data.
    :param mid: The middle frame instance, used to check if buy/sell flag is still True.
    :param low: The low frame instance, used to set limit/stop-loss borders.
    :param cond: Condition sell/buy
    """
    global condition, stop, limit, log, closing_price, runningLowFrame, buy_flag, sell_flag, pillow
    beeper('start')
    log = '{} Limit management. Setting {}min low frame {} limits.'.format(time_stamp(time.time()), low.interval, cond)
    logging.info(log)
    logs.append(log + '<br>')
    high_f = high_frame_indicators(high.get_frame())
    mid_f = mid_frame_indicators(mid.get_frame())
    low_f = low_frame_indicators(low.get_frame())
    limit = low_f.iloc[-1]['high'] + low_f.iloc[-1]['atr']
    stop = low_f.iloc[-1]['low'] - low_f.iloc[-1]['atr']
    closing_price = low_f.iloc[-1]['close']
    candle_time = low_f.iloc[-1]['time']
    log = '{} Current price {}. limit: {}. Stop loss: {}'.format(time_stamp(time.time()), closing_price, limit, stop)
    logging.info(log)
    logs.append(log + '<br>')
    if cond == 'buy':
        log = '{} Please wait 1 low candle time and give buy order if price exceeds {}. Wait {}min.' \
            .format(time_stamp(time.time()), limit, low.interval)
    elif cond == 'sell':
        log = '{} Please wait 1 low candle time and give sell order if price under {}. Wait {}min.' \
            .format(time_stamp(time.time()), stop, low.interval)
    logging.info(log)
    logs.append(log + '<br>')
    log = '{} Waiting until next {}min candle close.'.format(time_stamp(time.time()), low.interval)
    logging.info(log)
    logs.append(log + '<br>')
    chart_data(high_f, mid_f, low_f)
    time.sleep(low.candle)
    while True:
        high_f = high_frame_indicators(high.get_frame())
        mid_f = mid_frame_indicators(mid.get_frame())
        low_f = low_frame_indicators(low.get_frame())
        buy_flag = mid_f.iloc[-1]['buy flag']
        sell_flag = mid_f.iloc[-1]['sell flag']
        new_limit = low_f.iloc[-1]['high'] + low_f.iloc[-1]['atr']
        new_stop = low_f.iloc[-1]['low'] - low_f.iloc[-1]['atr']
        closing_price = low_f.iloc[-1]['close']
        chart_data(high_f, mid_f, low_f)
        new_candle_time = low_f.iloc[-1]['time']
        if break_event.is_set():  # thread "kill" by user
            log = '{} Operation interrupted by user.'.format(time_stamp(time.time()))
            logging.info(log)
            logs.append(log + '<br>')
            break
        elif cond == 'buy':
            if buy_flag:
                if new_candle_time > candle_time + low.candle:  # wait one candle to close
                    if closing_price > limit:
                        log = '{} Closing price exceeded limit. Please add buy order'.format(time_stamp(time.time()))
                        logging.info(log)
                        logs.append(log + '<br>')
                        beeper(cond)
                        if mode == 'simulator':
                            logging.info('')
                            logs.append('<br>')
                            pillow = closing_price * 0.975
                            log = '{} Bought at: {}.'.format(time_stamp(time.time()), closing_price)
                            logging.info(log)
                            logs.append(log + '<br>')
                            trades.append(log + '<br>')
                            condition = 'sell'
                        runningLowFrame = None
                        break
                    else:
                        candle_time = low_f.iloc[-2]['time']
                        if new_limit < limit:
                            limit = new_limit
                            stop = new_stop
                            log = '{} New limit set to {}. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), limit, low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                        else:
                            log = '{} Closing price not exceeded limit. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                else:
                    time.sleep(60)
            else:
                log = '{} Conditions re-evaluation.'.format(time_stamp(time.time()))
                logging.info(log)
                logs.append(log + '<br>')
                beeper('break')
                limit = None
                stop = None
                break
        elif cond == 'sell':
            if closing_price < pillow:
                log = '{} Sold pillow at: {}'.format(time_stamp(time.time()), closing_price)
                logging.info(log)
                logs.append(log + '<br>')
                trades.append(log + '<br>')
                condition = 'buy'
                limit = None
                stop = None
                pillow = 0
                break
            elif sell_flag:
                if new_candle_time > candle_time + low.candle:  # wait one candle to close
                    if closing_price < stop:
                        log = '{} Closing price under stop loss. Please add sell order' \
                            .format(time_stamp(time.time()))
                        logging.info(log)
                        logs.append(log + '<br>')
                        beeper(cond)
                        if mode == 'simulator':
                            logging.info('')
                            logs.append('<br>')
                            log = '{} Sold at: {}'.format(time_stamp(time.time()), closing_price)
                            logging.info(log)
                            logs.append(log + '<br>')
                            trades.append(log + '<br>')
                            condition = 'buy'
                        limit = None
                        stop = None
                        pillow = 0
                        break
                    else:
                        candle_time = low_f.iloc[-2]['time']
                        if new_stop > stop:
                            limit = new_limit
                            stop = new_stop
                            log = '{} New stop-loss set to {}. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), stop, low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                        else:
                            log = '{} Closing price over stop-loss level. Waiting until next {}min candle close.' \
                                .format(time_stamp(time.time()), low.interval)
                            logging.info(log)
                            logs.append(log + '<br>')
                else:
                    time.sleep(60)
            elif sell_flag is not True:
                log = '{} Conditions re-evaluation.'.format(time_stamp(time.time()))
                logging.info(log)
                logs.append(log + '<br>')
                beeper('break')
                limit = None
                stop = None
                break


def elderbot(mode, crypto_currency, fiat_currency, depth):
    global bot_mode, condition, log, crypto_balance, fiat_balance, closing_price, \
        runningHighFrame, runningMidFrame, runningLowFrame, trend, buy_flag, sell_flag
    licence = True  # check()['license_active']
    bot_mode = mode
    if licence:
        log = 'Your product licence is active. Thank you for using Hermes.'
        logging.info(log)
        logs.append(log + '<br>')
        if mode == 'simulator':
            condition = 'buy'
        i1d = Api(crypto_currency, fiat_currency, 1440, depth)
        i1h = Api(crypto_currency, fiat_currency, 60, depth)
        i15m = Api(crypto_currency, fiat_currency, 15, depth)
        log = '{} Operation start. Mode is {}.'.format(time_stamp(time.time()), mode)
        logging.info(log)
        logs.append(log + '<br>')
        hf = i1d
        mf = i1h
        lf = i15m
        runningHighFrame = '1 Day'
        runningMidFrame = '1 Hour'
        runningLowFrame = '15 minutes'
        while True:
            high_frame = high_frame_indicators(hf.get_frame())
            mid_frame = mid_frame_indicators(mf.get_frame())
            low_frame = low_frame_indicators(lf.get_frame())
            if break_event.is_set():  # thread "kill" by user
                cancel_order()
                log = '{} Breaking operation.'.format(time_stamp(time.time()))
                logging.info(log)
                logs.append(log + '<br>')
                break
            closing_price = low_frame.iloc[-1]['close']
            if mode == 'consulting' or mode == 'trading':
                condition, crypto_balance, fiat_balance = get_condition(crypto_currency, fiat_currency, closing_price)
            log = '{} Condition is {}.'.format(time_stamp(time.time()), condition)
            logging.info(log)
            logs.append(log + '<br>')
            trend = high_frame.iloc[-1]['trend']
            buy_flag = mid_frame.iloc[-1]['buy flag']
            sell_flag = mid_frame.iloc[-1]['sell flag']
            chart_data(high_frame, mid_frame, low_frame)
            if condition == 'buy':
                if trend:
                    log = '{} {} trend is {}'.format(time_stamp(time.time()), runningHighFrame, trend)
                    logging.info(log)
                    logs.append(log + '<br>')
                    if buy_flag:
                        log = '{} {} momentum is {}.'.format(time_stamp(time.time()), runningMidFrame, buy_flag)
                        logging.info(log)
                        logs.append(log + '<br>')
                        if mode == 'trading':
                            order_manager('market', hf, mf, lf, condition, crypto_currency, fiat_currency)
                        elif mode == 'consulting' or mode == 'simulator':
                            limit_manager(mode, hf, mf, lf, condition)
                    else:
                        log = '{} {} momentum is {}. Wait 1 min.'.format(time_stamp(time.time()),
                                                                         runningMidFrame, buy_flag)
                        logging.info(log)
                        logs.append(log + '<br>')
                        time.sleep(60)
                else:
                    log = '{} {} trend is {}. No buying opportunity. Wait 1 min.' \
                        .format(time_stamp(time.time()), runningHighFrame, trend)
                    logging.info(log)
                    logs.append(log + '<br>')
                    time.sleep(60)
            elif condition == 'sell':
                if trend:
                    log = '{} {} trend is {}.'.format(time_stamp(time.time()), runningHighFrame, trend)
                    logging.info(log)
                    logs.append(log + '<br>')
                    if sell_flag:
                        log = '{} {} sell flag is {}.'.format(time_stamp(time.time()), runningMidFrame, sell_flag)
                        logging.info(log)
                        logs.append(log + '<br>')
                        if mode == 'trading':
                            order_manager('market', hf, mf, lf, condition, crypto_currency, fiat_currency)
                        elif mode == 'consulting' or mode == 'simulator':
                            limit_manager(mode, hf, mf, lf, condition)
                    else:
                        log = '{} {} sell flag is {}. Wait 1 minute.'.format(time_stamp(time.time()),
                                                                             runningMidFrame, sell_flag)
                        logging.info(log)
                        logs.append(log + '<br>')
                        time.sleep(60)
                else:
                    log = '{} High-frame trend is negative.'.format(time_stamp(time.time()))
                    logging.info(log)
                    logs.append(log + '<br>')
                    if mode == 'trading':
                        order_manager('market', hf, mf, lf, condition, crypto_currency, fiat_currency)
                    elif mode == 'consulting' or mode == 'simulator':
                        limit_manager(mode, hf, mf, lf, condition)
    else:
        activation()
        log = 'Your product licence is not active.' \
              ' Please activate or contact technical support. ' \
              'Hermes_algotrading@proton.me'
        logging.info(log)
        logs.append(log + '<br>')
        exit()


def data_feed():
    if len(logs) > 300:
        del logs[:len(logs) - 299]
    return {
        'log': log,
        'logs': logs,
        'trades': trades,
        'condition': condition,
        'mode': bot_mode,
        'crypto_balance': crypto_balance,
        'fiat_balance': fiat_balance,
        'runningHighFrame': runningHighFrame,
        'runningMidFrame': runningMidFrame,
        'runningLowFrame': runningLowFrame,
        'high_chart_data': high_chart_data,
        'mid_chart_data': mid_chart_data,
        'high_ema1': high_ema1,
        'mid_k': mid_k,
        'mid_d': mid_d,
        'mid_rsi': mid_rsi,
        'low_chart_data': low_chart_data,
        'trend': str(trend),
        'buy_flag': str(buy_flag),
        'sell_flag': str(sell_flag),
        'price': closing_price,
        'low_limit': low_limit,
        'low_stop': low_stop,
        'low_atr': low_atr
    }

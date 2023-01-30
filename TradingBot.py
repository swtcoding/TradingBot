import ibapi
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract # ib uses contract objects to stream a real-time or historical data
from ibapi.order import *
import threading
import time
import talib
import numpy as np
import pandas as pd
import pytz
import math
from datetime import datetime, timedelta

# Vars
orderId = 1


# Class for Interactive Brokers Connection
class IBapi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
    
    # Historical Backtest Data
    def historicalData(self, reqId, bar):
        bot.on_bar_update(reqId, bar, False)
    
    # On Realtime Bar after historical data finishes
    def historicalDataUpdate(self, reqId, bar):
        bot.on_bar_update(reqId, bar, True)
        return
    
    # On Historical Data end
    def historicalDataEnd(self, reqId, start, end):
        print(reqId)
    
    # Get next order Id we can use
    def nextValidId(self, nextorderId):
        global orderId
        orderId = nextorderId

    # Listen for realTimeBars
    def realtimeBar(self, reqId, time, open_, high, low, close, volume, wap, count):
        bot.on_bar_update(reqId, time, open_, high, low, close, volume, wap, count)

# Bar Object will handle the data that is coming from Ib
class Bar:
    open = 0
    low = 0
    high = 0
    close = 0
    volume = 0
    date = ''

    def __init__(self):
        self.open = 0
        self.low = 0
        self.high = 0
        self.close = 0
        self.volume = 0
        self.date = ''
# Bot
class Bot:
    ib = None
    barSize = 0
    currentBar = Bar()
    bars = []
    reqId = 1
    global orderId
    smaPeriod = 50
    symbol = ""
    initialBarTime = datetime.now().astimezone(pytz.timezone("America/New_York"))

    def __init__(self):
        self.ib = IBapi()
        self.ib.connect('127.0.0.1', 7496, 1)
        # This allows us to seperate the sockets, whenever we are listening to data we can still continue other applications
        ib_thread = threading.Thread(target=self.run_loop, daemon=True)
        ib_thread.start()
        time.sleep(1)

        # Create Ib contract object
        self.symbol = input("Enter the symbol you want to trade: ")
        
        # Get bar size
        self.barSize = input("Enter the barsize you want to trade in minutes: ")
        min_text = " min"
        if (int(self.barSize > 1)):
            min_text = " mins"
        query_time = (datetime.now().astimezone(pytz.timezone("America/New_York") - timedelta(days=1).replace(hour=16, minute=0, second=0, microsecond=0)).strftime("%Y%m%d %H:%M:%S"))
        contract = Contract()
        contract.symbol = self.symbol.upper()
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"
        # Request real time market data
        '''self.ib.reqRealTimeBars(0, contract, 5, "TRADES", 1, [])'''
        # Start streaming after having recorded all the historical data
        self.ib.reqHistoricalData(self.reqId, contract, "", "2 D", str(self.barSize) + min_text, 1, 1, True, [])

    # Listen to socket in a seperate thread
    def run_loop(self):
        self.ib.run()
    
    # Bracket Order Setup
    def bracketOrder(self, parentOrderId, action, quantity, profitTarget, stoploss):
        # Initial Entry
        contract = Contract()
        contract.symbol = self.symbol.upper()
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"

        # Create Parent Order
        parent = Order()
        parent.orderId = parentOrderId
        parent.orderType = "MKT"
        parent.action = action
        parent.totalQuantity = quantity
        parent.transmit = False

        # Profit Target
        profitTargetOrder = Order()
        profitTargetOrder.orderId = parent.orderId + 1
        profitTargetOrder.orderType = "LMT"
        profitTargetOrder.action = "SELL"
        profitTargetOrder.totalQuantity = quantity
        profitTargetOrder.lmtPrice = round(profitTargetOrder, 2)
        profitTargetOrder.transmit = False

        # Stop Loss
        stopLossOrder = Order()
        stopLossOrder.orderId = parent.orderId + 2
        stopLossOrder.orderType = "STP"
        stopLossOrder.action = "SELL"
        stopLossOrder.totalQuantity = quantity
        stopLossOrder.auxPrice = round(stoploss, 2)
        stopLossOrder.transmit = True
    
        bracketOrders = [parent, profitTargetOrder, stopLossOrder]
        return bracketOrders
    # Pass real-time bar data back to the bot object
    def on_bar_update(self, reqId, bar, realtime):
        # Historical data to catch up
        if realtime == False:
            self.bars.append(bar)
        else: # Real time now
            bartime = datetime.strptime(bar.date, "%Y%m%d %H:%M:%S").astimezone(pytz.timezone("America/New_York"))
            mins_diff = (bartime - self.initialBarTime).total_seconds() / 60.0
            self.currentBar.date = bartime
            # On bar close
            if (mins_diff > 0) and math.floor(mins_diff) % self.barSize == 0:
                # Entry - if we have a higher high, a higher low and we cross the 50 sma buy
                # 1) SMA
                closes = []
                for bar in self.bars:
                    closes.append(bar.close)
                self.close_array = pd.Series(np.asarray(closes))
                self.sma = talib.trend.sma(self.close_array, self.smaPeriod, True)
                print("SMA :" + str(self.sma[len(self.sma) - 1]))

                # 2) Calculate higher highs and lows
                last_low = self.bars[len(self.bars) - 1].low
                last_high = self.bars[len(self.bars) - 1].high
                last_close = self.bars[len(self.bars) - 1].close
                last_bar = self.bars[len(self.bars) - 1]

                if (bar.close > last_high 
                    and self.currentBar.low > last_low
                    and bar.close > self.sma[len(self.sma) - 1]
                    and last_close < self.sma[len(self.sma) - 1]):

                    #Bracket Order 5% Profit target 3% Stop Loss
                    profit_target = bar.close * 1.05
                    stop_loss = bar.close * 0.97
                    quantity = 1
                    bracket = self.bracketOrder(orderId, "BUY", quantity, profit_target, stop_loss)
                    # Place bracket order 
                    for o in bracket:
                        o.ocaGroup = "OCA_" + str(orderId)
                        o.ocaType = 2
                        self.ib.placeOrder(o.orderId, contract, o)


bot = Bot()
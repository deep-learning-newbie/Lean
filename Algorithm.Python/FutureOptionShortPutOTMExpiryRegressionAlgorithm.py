# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License

from datetime import datetime, timedelta

import clr
from System import *
from System.Reflection import *
from QuantConnect import *
from QuantConnect.Algorithm import *
from QuantConnect.Data import *
from QuantConnect.Data.Market import *
from QuantConnect.Orders import *
from QuantConnect.Securities import *
from QuantConnect.Securities.Future import *
from QuantConnect import Market


### <summary>
### This regression algorithm tests Out of The Money (OTM) future option expiry for short puts.
### We expect 1 order from the algorithm, which are:
###
###   * Initial entry, sell ES Put Option (expiring OTM)
###     - Profit the option premium, since the option was not assigned.
###
### Additionally, we test delistings for future options and assert that our
### portfolio holdings reflect the orders the algorithm has submitted.
### </summary>
class FutureOptionShortPutOTMExpiryRegressionAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2020, 3, 1)
        clr.GetClrType(QCAlgorithm).GetField("_endDate", BindingFlags.NonPublic | BindingFlags.Instance).SetValue(self, DateTime(2021, 3, 30))
        
        start = datetime(2020, 9, 22)

        # We add AAPL as a temporary workaround for https://github.com/QuantConnect/Lean/issues/4872
        # which causes delisting events to never be processed, thus leading to options that might never
        # be exercised until the next data point arrives.
        self.AddEquity("AAPL", Resolution.Daily)

        self.es19h21 = self.AddFutureContract(
            Symbol.CreateFuture(
                Futures.Indices.SP500EMini,
                Market.CME,
                datetime(2021, 3, 19)),
            Resolution.Minute).Symbol

        self.Log('lookup')
        # Select a future option expiring ITM, and adds it to the algorithm.
        self.esOption = self.AddFutureOptionContract(
            list(
                sorted(
                    [x for x in self.OptionChainProvider.GetOptionContractList(self.es19h21, start) if x.ID.StrikePrice >= 3200.0 and x.ID.OptionRight == OptionRight.Put],
                    key=lambda x: x.ID.StrikePrice
                )
            )[0], Resolution.Minute).Symbol

        self.Log("Creation")

        self.expectedContract = Symbol.CreateOption(self.es19h21, Market.CME, OptionStyle.American, OptionRight.Put, 3200.0, datetime(2021, 3, 19))
        if self.esOption != self.expectedContract:
            raise AssertionError(f"Contract {self.expectedContract} was not found in the chain");

        self.Log("Schedule")
        self.Schedule.On(self.DateRules.On(start.year, start.month, start.day), self.TimeRules.AfterMarketOpen(self.es19h21, 1), self.ScheduledMarketOrder)

    def ScheduledMarketOrder(self):
        self.MarketOrder(self.esOption, -1)

    def OnData(self, data: Slice):
        # Assert delistings, so that we can make sure that we receive the delisting warnings at
        # the expected time. These assertions detect bug #4872
        for delisting in data.Delistings.Values:
            if delisting.Type == DelistingType.Warning:
                if delisting.Time != datetime(2021, 3, 19):
                    raise AssertionError(f"Delisting warning issued at unexpected date: {delisting.Time}");

            if delisting.Type == DelistingType.Delisted:
                if delisting.Time != datetime(2021, 3, 20):
                    raise AssertionError(f"Delisting happened at unexpected date: {delisting.Time}");
        

    def OnOrderEvent(self, orderEvent: OrderEvent):
        if orderEvent.Status != OrderStatus.Filled:
            # There's lots of noise with OnOrderEvent, but we're only interested in fills.
            return

        if not self.Securities.ContainsKey(orderEvent.Symbol):
            raise AssertionError(f"Order event Symbol not found in Securities collection: {orderEvent.Symbol}")

        security = self.Securities[orderEvent.Symbol]
        if security.Symbol == self.es19h21:
            raise AssertionError(f"Expected no order events for underlying Symbol {security.Symbol}")

        if security.Symbol == self.expectedContract:
            self.AssertFutureOptionContractOrder(orderEvent, security)

        else:
            raise AssertionError(f"Received order event for unknown Symbol: {orderEvent.Symbol}")

        self.Log(f"{orderEvent}");

    def AssertFutureOptionContractOrder(self, orderEvent: OrderEvent, optionContract: Security):
        if orderEvent.Direction == OrderDirection.Sell and optionContract.Holdings.Quantity != -1:
            raise AssertionError(f"No holdings were created for option contract {optionContract.Symbol}")

        if orderEvent.Direction == OrderDirection.Buy and optionContract.Holdings.Quantity != 0:
            raise AssertionError("Expected no options holdings after closing position")

        if orderEvent.IsAssignment:
            raise AssertionError(f"Assignment was not expected for {orderEvent.Symbol}")

    def OnEndOfAlgorithm(self):
        if self.Portfolio.Invested:
            raise AssertionError(f"Expected no holdings at end of algorithm, but are invested in: {', '.join([str(i.ID) for i in self.Portfolio.Keys])}")
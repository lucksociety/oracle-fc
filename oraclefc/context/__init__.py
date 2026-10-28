"""Match-context layer: lineups, injuries/suspensions, player ratings, rest/congestion,
travel, weather and xG. Every source here is non-market (see governance.PERMITTED_PROVIDERS).

Context enters a forecast only as a *log-rate adjustment* (exponential tilt) of the
champion's joint score matrix, with coefficients learned out of sample
(``oraclefc.run_context_backtest``) — or, where no point-in-time history exists, a
documented conservative prior that is flagged in every report.
"""

# Futu 10.10 API probe — 2026-08-23

| method | result | detail | columns |
|---|---|---|---|
| `get_option_market_statistic` | OK | 249 rows | time, timestamp, call_value, put_value, total_value, ratio |
| `get_option_event` | OK | {'event_list':              option_code  ...          concept_plate_list
0    US.GLD260911C430000  ...              [US. |  |
| `get_option_rank` | EXC | TypeError: OpenQuoteContext.get_option_rank() missing 1 required positional argument: 'sort_type' |  |
| `get_option_underlying_rank` | EXC | TypeError: OpenQuoteContext.get_option_underlying_rank() missing 1 required positional argument: 'sort_type' |  |
| `get_option_volatility` | OK | 20 rows | timestamp, timestamp_str, implied_volatility, history_volatility, volatility_premium, average_impvol, impvol_status, analysis |
| `get_option_exercise_probability` | OK | 23 rows | timestamp, timestamp_str, security_price, strike_probability |
| `get_earnings_calendar` | OK | 300 rows | security, name, earnings_date, earnings_timestamp, pub_type, period_text, eps_actual, eps_predict, revenue_actual, revenue_predict, ebit_actual, ebit_predict, option_volume, iv, iv_rank, iv_percentile, market_cap, price |
| `get_dividend_calendar` | EXC | TypeError: OpenQuoteContext.get_dividend_calendar() got an unexpected keyword argument 'begin_date' |  |
| `get_economic_calendar` | EXC | TypeError: OpenQuoteContext.get_economic_calendar() got an unexpected keyword argument 'market' |  |
| `get_top_movers_rank` | OK | (1846,    security  ... volume_ratio
0  US.IDKOY  ...        1.746
1   US.HOOD  ...        2.780
2  US.TISCY  ...        |  |
| `get_hot_list` | OK | (8643,   security  ...                                           news_url
0  US.BABA  ...  https://news.futunn.com/post/ |  |
| `get_search_quote` | OK | 10 rows | market, code, name, sec_type, is_watched |
| `get_search_news` | OK | 5 rows | title, news_sub_type, source, publish_time, view_count, related_securities, url |
| `get_fed_watch_target_rate` | OK | 57 rows | meeting_date, target_range, probability |
| `get_fed_watch_dot_plot` | OK | 17 rows | year, rate, vote_count, is_median, median_rate, current_rate |
| `get_macro_indicator_list` | EXC | TypeError: OpenQuoteContext.get_macro_indicator_list() missing 1 required positional argument: 'region' |  |
| `get_institution_holding_change` | EXC | TypeError: OpenQuoteContext.get_institution_holding_change() got an unexpected keyword argument 'code' |  |
| `get_ark_fund_holding` | OK | 20 rows | security, name, shares, shares_change, market_value, weight, weight_change |
| `get_stock_screen` | EXC | TypeError: OpenQuoteContext.get_stock_screen() got an unexpected keyword argument 'market' |  |
| `get_capital_flow` | OK | 391 rows | last_valid_time, in_flow, super_in_flow, big_in_flow, mid_in_flow, sml_in_flow, main_in_flow, capital_flow_item_time |
| `get_capital_distribution` | OK | 1 rows | capital_in_super, capital_in_big, capital_in_mid, capital_in_small, capital_out_super, capital_out_big, capital_out_mid, capital_out_small, update_time |
| `get_rehab` | OK | 2 rows | ex_div_date, split_base, split_ert, join_base, join_ert, split_ratio, per_cash_div, special_dividend, bonus_base, bonus_ert, per_share_div_ratio, transfer_base, transfer_ert, per_share_trans_ratio, allot_base, allot_ert, allotment_ratio, allotment_price, add_base, add_ert, stk_spo_ratio, stk_spo_price, spin_off_base, spin_off_ert, spin_off_ratio, forward_adj_factorA, forward_adj_factorB, backward_adj_factorA, backward_adj_factorB |
| `get_owner_plate` | OK | 33 rows | code, name, plate_code, plate_name, plate_type |

"""Realistic IBKR Activity Statement test fixture based on actual export format.

This fixture contains anonymized but structurally accurate IBKR data with all columns
present as they appear in a real Activity Statement CSV export.
"""

# fmt: off
# Realistic IBKR Activity Statement with full column structure
# Based on actual IBKR export format - values anonymized but structure preserved
REALISTIC_IBKR_CSV = "\n".join([
    # Statement section
    "Statement,Header,Field Name,Field Value",
    "Statement,Data,BrokerName,Interactive Brokers Ireland Limited",
    "Statement,Data,BrokerAddress,",
    "Statement,Data,Title,Activity Statement",
    "Statement,Data,Period,January 1 - January 31 2026",
    "Statement,Data,WhenGenerated,2026-02-04 11:14:16 EST",

    # Account Information section
    "Account Information,Header,Field Name,Field Value",
    "Account Information,Data,Name,Test User",
    "Account Information,Data,Account,U12345678",
    "Account Information,Data,Account Type,Individual",
    "Account Information,Data,Base Currency,EUR",

    # Net Asset Value section
    "Net Asset Value,Header,Asset Class,Prior Total,Current Long,Current Short,Current Total,Change",
    "Net Asset Value,Data,Cash,2.97,2.97,0,2.97,0",
    "Net Asset Value,Data,Stock,13223.64,13765.22,0,13765.22,541.58",
    "Net Asset Value,Data,Total,13226.61,13768.19,0,13768.19,541.58",

    # Open Positions section - this is the key section we parse
    # Header row defines column positions
    "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,"
    "Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Code",
    # Data rows - Summary rows contain actual positions
    "Open Positions,Data,Summary,Stocks,USD,AMZN,10.5041,1,"
    "179.655789073,1887.122374,239.3,2513.63,626.507625,",
    "Open Positions,Data,Summary,Stocks,USD,ASTS,6.4284,1,"
    "28.156101518,180.998683,111.21,714.9,533.901318,",
    "Open Positions,Data,Summary,Stocks,USD,AXP,0.8439,1,"
    "238.174974523,200.995861,352.17,297.2,96.204139,",
    "Open Positions,Data,Summary,Stocks,USD,CSPX,13.4888,1,"
    "595.321206557,8030.168691,743.28,10025.96,1995.791309,",
    "Open Positions,Data,Summary,Stocks,USD,SMH,38,1,"
    "41.058684211,1560.23,72.64,2760.32,1200.09,",
    # Total rows should be skipped
    "Open Positions,Total,Stocks,USD,11859.515609,16312.01,4452.494391",
    "Open Positions,Total,Stocks,EUR,10007.889436967,13765.2158787,3757.326441733",

    # Financial Instrument Information section - provides asset type and name
    "Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,"
    "Security ID,Underlying,Listing Exch,Multiplier,Type,Code",
    "Financial Instrument Information,Data,Stocks,AMZN,AMAZON.COM INC,3691937,"
    "US0231351067,AMZN,NASDAQ,1,COMMON,",
    "Financial Instrument Information,Data,Stocks,ASTS,AST SPACEMOBILE INC,480745767,"
    "US00217D1000,ASTS,NASDAQ,1,COMMON,",
    "Financial Instrument Information,Data,Stocks,AXP,AMERICAN EXPRESS CO,4721,"
    "US0258161092,AXP,NYSE,1,COMMON,",
    "Financial Instrument Information,Data,Stocks,CSPX,ISHARES CORE S&P 500,76023663,"
    "IE00B5BMR087,CSPX,LSEETF,1,ETF,",
    "Financial Instrument Information,Data,Stocks,SMH,VANECK SEMICONDUCTOR ETF,458512500,"
    "IE00BMC38736,SMH,LSEETF,1,ETF,",

    # Notes section (should be ignored)
    "Notes/Legal Notes,Header,Type,Note",
    "Notes/Legal Notes,Data,Notes,Stock exchange transactions generally settle on T+1.",
])
# fmt: on

# Expected parsed holdings from REALISTIC_IBKR_CSV
EXPECTED_HOLDINGS = [
    {"ticker": "AMZN", "qty": "10.5041", "currency": "USD", "asset_type": "equity", "name": "AMAZON.COM INC"},
    {"ticker": "ASTS", "qty": "6.4284", "currency": "USD", "asset_type": "equity", "name": "AST SPACEMOBILE INC"},
    {"ticker": "AXP", "qty": "0.8439", "currency": "USD", "asset_type": "equity", "name": "AMERICAN EXPRESS CO"},
    {"ticker": "CSPX", "qty": "13.4888", "currency": "USD", "asset_type": "etf", "name": "ISHARES CORE S&P 500"},
    {"ticker": "SMH", "qty": "38", "currency": "USD", "asset_type": "etf", "name": "VANECK SEMICONDUCTOR ETF"},
]

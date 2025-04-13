# EarningsEdgeDetection

A sophisticated scanner for identifying high-probability earnings trades based on volatility term structure and other key metrics.

## Features

* Multi-tier trade categorization system
* Strict filtering criteria for high-quality trade selection
* Automatically determines relevant earnings dates based on current time
* Scans both post-market and pre-market earnings announcements
* Performance optimized scanning process
* Comprehensive metrics tracking

## Trade Categories

The scanner organizes results into three categories:

1. **TIER 1 RECOMMENDED TRADES**
   - Meets all core filtering criteria
   - Term structure <= -0.004 (required for all categories)
   - Highest probability setups

2. **TIER 2 RECOMMENDED TRADES**
   - Near misses with term structure <= -0.006
   - Has exactly one near-miss criteria failure
   - Term structure <= -0.004 (required for all categories)

3. **NEAR MISSES**
   - Meets most criteria with minor issues
   - Term structure <= -0.004 (required for all categories)
   - Good candidates to watch

## Installation
 
1. Clone the repository:
```bash
git clone [repository-url]
cd EarningsEdgeDetection/cli_scanner
```
 
2. Create and activate a virtual environment (not required, I personally don't but generally it is recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
 
3. Install required packages:
```bash
pip install -r requirements.txt
```
 
4. Install Chrome WebDriver (required for Market Chameleon scraping):
   - The script will automatically download the appropriate ChromeDriver version
   - Ensure you have Google Chrome installed on your system
  
    
5. Also install webdriver_manager (this you must do manually via the following command):
   
      ```pip install webdriver-manager```
 
## Usage

Prerequisite:

Make sure (within the cli_scanner folder) you run ```chmod +x ./run.sh``` before proceeding so that you don't run into a permissions issue

Basic usage:
```bash
./run.sh [MM/DD/YYYY]
```

The run.sh script automatically detects the optimal number of worker threads for your system.

To run manually with custom settings:
```bash
python scanner.py --date "04/20/2025" --parallel 4
```

Optional parameters:
- `--date`, `-d`: Specific date to scan in MM/DD/YYYY format
- `--parallel`, `-p`: Number of worker threads (0 disables parallel processing)

## Filtering Criteria

### Hard Filters (No Exceptions)
- Stock price >= $10.00
- Options expiration <= 9 days away
- Open interest >= 1000 contracts (combined calls/puts)
- Term structure <= -0.004 (for ALL categories, including near misses)
- Options availability: Must have options chain
- Core analysis: Must complete successfully

### Additional Criteria
- Average daily volume >= 1.5M shares
- Winrate >= 50% (40-50% is near miss/Tier 2 eligible)
- IV/RV ratio >= 1.25 (preferred)

### Near Miss Ranges
1. Price
   - Pass: >= $10.00 (hard filter)
   - Fail: < $10.00

2. Volume (30-day average)
   - Pass: ≥ 1,500,000
   - Near Miss: 1,000,000 - 1,499,999
   - Fail: < 1,000,000

3. Winrate (previously Market Chameleon Overestimate)
   - Pass: >= 50%
   - Near Miss: 40-49.9%
   - Fail: < 40%

4. IV/RV Ratio
   - Pass: ≥ 1.25
   - Near Miss: 1.00 - 1.24
   - Fail: < 1.00

## Performance Optimizations in the New Version (feel free to skip to next section)

1. **Filter Chain Ordering**
   - do the most important filter group first
   - exiting on any failure instead of continuing to compute all filters
   - ordering filter execution from fastest to slowest to catch unfavorable trades quickly

2. **Parallel Processing**
   - Multi-threaded stock analysis
   - Automatic detection of optimal thread count
   - Configurable via --parallel flag
   - Parallelized earnings data fetching

3. **Browser Efficiency**
   - Reuses single headless browser instance
   - Faster page loading process

4. **Additional Efficiency Improvements**
   - Reduced sleep time between batches (5 seconds)
   - Conditional execution of expensive operations (skip Market Chameleon if already failed)
   - Early exit on critical filter failures (price, expiration, term structure)
   - List comprehensions for faster data filtering

## Output Explanation
 
For each stock, the following metrics are displayed:
* Current price
* 30-day average volume
* Winrate: Percentage and number of earnings periods analyzed
* IV/RV ratio
* Term structure (volatility curve slope)

## Time-Based Logic
 
 If run before 4 PM Eastern:
  - Checks today's post-market earnings
  - Checks tomorrow's pre-market earnings
 
 If run after 4 PM Eastern:
  - Checks tomorrow's post-market earnings
  - Checks the following day's pre-market earnings
 
## Troubleshooting
 
Common issues:
 
1. Chrome WebDriver errors:
   - Ensure Google Chrome is installed
   - Try clearing your browser cache
   - Check Chrome version matches driver version
 
2. Rate limiting:
   - The script includes delays to avoid rate limiting
   - If you see connection errors, try increasing delay times
 
3. Market hours:
   - The scanner uses Eastern Time (ET) for market hours
   - Ensure your system clock is accurate
 
## Logs
 
 Logs are stored in the `logs` directory
 Each run creates a dated log file
 Check logs for detailed error information and debugging

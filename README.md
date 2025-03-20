# EarningsEdgeDetection

## Features
 * Automatically determines relevant earnings dates based on current time
 
 * Scans both post-market and pre-market earnings announcements
 
 * Applies multiple filtering criteria for stock selection
 
 * Identifies both recommended stocks and "near miss" candidates
 
 * Provides detailed metrics for each stock
 
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
./run.sh
```
 
With specific date:
```bash
python scanner.py -d MM/DD/YYYY
```
 
## Filtering Criteria
 
The scanner applies the following filters:
 
### Mandatory Checks
 Options availability: Must have options chain
 
 Core analysis: Must complete successfully
 
### Standard Filters
Each filter has pass/fail criteria and some have "near miss" ranges:
 
1. Price
   - Pass: ≥ $7.00
   - Near Miss: $5.00 - $6.99
   - Fail: < $5.00
 
2. Volume (30-day average)
   - Pass: ≥ 1,500,000
   - Near Miss: 1,000,000 - 1,499,999
   - Fail: < 1,000,000
 
3. Market Chameleon Overestimate (how often was selling earnings volatility profitable in the past 2-3 years on this stock)
   - Pass: ≥ 40%
   - Fail: < 40%
 
4. IV/RV Ratio
   - Pass: ≥ 1.25
   - Near Miss: 1.00 - 1.24
   - Fail: < 1.00
 
## Output Explanation
 
The scanner outputs two categories:
 
1. **Recommended Stocks**: Stocks that pass ALL criteria with no near misses
 
2. **Near Misses**: Stocks that:
   - Pass all mandatory checks
   - Have exactly ONE metric in the near-miss range
   - Pass all other criteria
 
For each stock, the following metrics are displayed:
 * Current price
 * 30-day average volume
 * Market Chameleon overestimate percentage
 * IV/RV ratio
 * Term structure (volatility curve slope)
 * Number of available options expirations
 * Next options expiration date
 
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


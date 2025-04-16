"""
Earnings scanner that handles date logic and filtering.
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

import pytz
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import yfinance as yf
from tqdm import tqdm

from .analyzer import OptionsAnalyzer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

class EarningsScanner:
    def __init__(self):
        self.analyzer = OptionsAnalyzer()
        self.batch_size = 10
        self.eastern_tz = pytz.timezone('US/Eastern')
        self.current_input_date = None
        self.iv_rv_pass_threshold = 1.25  # Default threshold
        self.iv_rv_near_miss_threshold = 1.0  # Default threshold
        self._driver = None
        self._driver_lock = None
        
    def __del__(self):
        # Clean up browser when scanner is destroyed
        if hasattr(self, '_driver') and self._driver is not None:
            try:
                self._driver.quit()
            except Exception as e:
                # Just silently ignore errors during cleanup
                pass
    
    def get_scan_dates(self, input_date: Optional[str] = None) -> Tuple[datetime.date, datetime.date]:
        if input_date:
            try:
                post_date = datetime.strptime(input_date, '%m/%d/%Y').date()
                pre_date = post_date + timedelta(days=1)
                logger.info(f"Using provided date: post-market {post_date}, pre-market {pre_date}")
            except ValueError as e:
                logger.error(f"Invalid date format: {e}")
                raise ValueError("Please provide date in MM/DD/YYYY format")
        else:
            now = datetime.now(self.eastern_tz)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
            post_date = now.date() if now < market_close else (now + timedelta(days=1)).date()
            pre_date = post_date + timedelta(days=1)

        return post_date, pre_date

    def fetch_earnings_data(self, date: datetime.date) -> List[Dict]:
        url = "https://www.investing.com/earnings-calendar/Service/getCalendarFilteredData"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': 'https://www.investing.com/earnings-calendar/'
        }
        
        payload = {
            'country[]': '5',
            'dateFrom': date.strftime('%Y-%m-%d'),
            'dateTo': date.strftime('%Y-%m-%d'),
            'currentTab': 'custom',
            'limit_from': 0
        }
        
        response = requests.post(url, headers=headers, data=payload)
        data = response.json()
        
        soup = BeautifulSoup(data['data'], 'html.parser')
        rows = soup.find_all('tr')
        
        stocks = []
        for row in rows:
            if not row.find('span', class_='earnCalCompanyName'):
                continue
            
            try:
                ticker = row.find('a', class_='bold').text.strip()
                timing_span = row.find('span', class_='genToolTip')
                
                if timing_span and 'data-tooltip' in timing_span.attrs:
                    tooltip = timing_span['data-tooltip']
                    if tooltip == 'Before market open':
                        timing = 'Pre Market'
                    elif tooltip == 'After market close':
                        timing = 'Post Market'
                    else:
                        timing = 'During Market'
                else:
                    timing = 'Unknown'
                
                stocks.append({'ticker': ticker, 'timing': timing})
                
            except Exception as e:
                logger.warning(f"Error parsing row: {e}")
                continue
        
        return stocks

    _driver = None  # Reusable browser instance
    _driver_lock = None  # Thread lock for browser access
    _max_retries = 3  # Number of retry attempts for browser operations
    
    def _initialize_browser(self):
        """Initialize or reinitialize the browser with optimized settings"""
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        # Close any existing instance first
        if self._driver is not None:
            try:
                self._driver.quit()
            except:
                pass
            self._driver = None
        
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-infobars')
        options.add_argument('--blink-settings=imagesEnabled=false')
        options.add_argument('--js-flags=--expose-gc')
        options.add_argument('--disable-dev-shm-usage')
        
        # Additional memory optimization
        options.add_argument('--disable-browser-side-navigation')
        options.add_argument('--disable-3d-apis')
        options.add_argument('--disable-accelerated-2d-canvas')
        options.add_argument('--disable-web-security')
        options.add_argument('--disable-features=NetworkPrediction,PrefetchDNSOverride')
        options.add_argument('--disable-sync')
        options.add_argument('--mute-audio')
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--memory-model=low')
        options.add_argument('--disable-translate')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        
        service = Service(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        self._driver.set_page_load_timeout(10)  # Even shorter timeout
        
    def check_mc_overestimate(self, ticker: str) -> Dict[str, any]:
        """Get Market Chameleon overestimate data with retry mechanism"""
        import threading
        
        # Initialize thread lock if needed
        if self._driver_lock is None:
            self._driver_lock = threading.Lock()
        
        # Default return values
        default_result = {'win_rate': 0.0, 'quarters': 0}
        
        # Acquire lock for thread safety
        with self._driver_lock:
            # Try to initialize browser if not already running
            if self._driver is None:
                try:
                    self._initialize_browser()
                except Exception as e:
                    logger.error(f"Failed to initialize browser: {e}")
                    return default_result
            
            # Retry loop
            retries = 0
            while retries < self._max_retries:
                try:
                    # Check if browser needs reinitializing
                    try:
                        # Quick test if browser is responsive
                        self._driver.window_handles
                    except:
                        # Browser crashed or not responsive, reinitialize
                        logger.info(f"Browser needs reinitializing for {ticker}")
                        self._initialize_browser()
                    
                    url = f"https://marketchameleon.com/Overview/{ticker}/Earnings/Earnings-Charts/"
                    self._driver.get(url)
                    
                    wait = WebDriverWait(self._driver, 8)  # Even shorter timeout
                    section = wait.until(
                        EC.presence_of_element_located((By.CLASS_NAME, "symbol-section-header-descr"))
                    )
            
                    # Default results
                    win_rate = 0.0
                    quarters = 0
                    
                    # Extract both the percentage and quarters data
                    spans = section.find_elements(By.TAG_NAME, "span")
                    for span in spans:
                        if "overestimated" in span.text:
                            # Extract the percentage
                            try:
                                strong = span.find_element(By.TAG_NAME, "strong")
                                win_rate = float(strong.text.strip('%'))
                                
                                # Extract the quarters by parsing the text after the percentage
                                text = span.text
                                quarters_pattern = r"in the last (\d+) quarters"
                                quarters_match = re.search(quarters_pattern, text)
                                if quarters_match:
                                    quarters = int(quarters_match.group(1))
                            except Exception as inner_e:
                                logger.debug(f"Error extracting data for {ticker}: {inner_e}")
                            break
                    
                    # Success - return the data and break the retry loop
                    return {
                        'win_rate': win_rate,
                        'quarters': quarters
                    }
                    
                except Exception as e:
                    logger.warning(f"Error getting MC data for {ticker} (attempt {retries+1}/{self._max_retries}): {e}")
                    retries += 1
                    
                    # Try to reinitialize browser after each failure
                    try:
                        self._initialize_browser()
                    except:
                        pass
                    
                    # Small delay before retry
                    time.sleep(1)
            
            # If we get here, we've exhausted retries
            logger.error(f"Failed to get MC data for {ticker} after {self._max_retries} attempts")
            return default_result

    def validate_stock(self, stock: Dict) -> Dict:
        ticker = stock['ticker']
        analysis = None
        failed_checks = []
        near_miss_checks = []
        metrics = {}
        
        try:
            yf_ticker = yf.Ticker(ticker)
            
            # Price check (first and fastest)
            current_price = yf_ticker.history(period='1d')['Close'].iloc[-1]
                
            metrics['price'] = current_price
            if current_price < 10.0:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Price ${current_price:.2f} < $10.00",
                    'metrics': {'price': current_price}
                }

            # Options availability and expiration check
            options_dates = yf_ticker.options
            if not options_dates:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': "No options available",
                    'metrics': {'price': current_price}
                }

            # Check expiration date
            first_expiry = datetime.strptime(options_dates[0], "%Y-%m-%d").date()
            days_to_expiry = (first_expiry - datetime.now().date()).days
            if days_to_expiry > 9:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Next expiration too far: {days_to_expiry} days",
                    'metrics': {'price': current_price, 'days_to_expiry': days_to_expiry}
                }

            # Check open interest
            chain = yf_ticker.option_chain(options_dates[0])
            total_oi = chain.calls['openInterest'].sum() + chain.puts['openInterest'].sum()
            if total_oi < 2000:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Insufficient open interest: {total_oi}",
                    'metrics': {'price': current_price, 'open_interest': total_oi}
                }
            
            metrics.update({
                'open_interest': total_oi,
                'days_to_expiry': days_to_expiry
            })
            
            # Mandatory check: core analysis
            analysis = self.analyzer.compute_recommendation(ticker)
                
            if "error" in analysis:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Analysis error - {analysis['error']}",
                    'metrics': {}
                }
            
            # Term structure check (immediate exit - this is a hard filter)
            term_slope = analysis.get('term_slope', 0)
            metrics['term_structure'] = term_slope
            if term_slope > -0.004:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Term structure {term_slope:.4f} > -0.004",
                    'metrics': metrics
                }
                
            # Check ATM option deltas to ensure they are not too far from 0.5
            call_delta = analysis.get('atm_call_delta')
            put_delta = analysis.get('atm_put_delta')
            
            if call_delta is not None and put_delta is not None:
                # Call delta should be <= 0.57 (not too deep ITM)
                # Put delta should be >= -0.57 (absolute value <= 0.57)
                if call_delta > 0.57 or abs(put_delta) > 0.57:
                    return {
                        'pass': False,
                        'near_miss': False,
                        'reason': f"ATM options have delta > 0.57 (call: {call_delta:.2f}, put: {put_delta:.2f})",
                        'metrics': metrics
                    }
            
            # Check for minimum expected move of $1.00
            expected_move_pct = analysis.get('expected_move', 'N/A')
            if expected_move_pct != 'N/A':
                # Parse the percentage from the string (e.g., "5.20%")
                try:
                    move_pct = float(expected_move_pct.strip('%')) / 100
                    expected_move_dollars = current_price * move_pct
                    metrics['expected_move_dollars'] = expected_move_dollars
                    
                    # Reject if expected move is less than $0.90
                    if expected_move_dollars < 0.9:
                        return {
                            'pass': False,
                            'near_miss': False,
                            'reason': f"Expected move ${expected_move_dollars:.2f} < $0.90",
                            'metrics': metrics
                        }
                except (ValueError, AttributeError):
                    logger.warning(f"Could not parse expected move for {ticker}: {expected_move_pct}")
            
            # Non-mandatory checks with near-miss ranges
            # Price check
            current_price = yf_ticker.history(period='1d')['Close'].iloc[-1]
            metrics['price'] = current_price
            if current_price < 5.0:
                failed_checks.append(f"Price ${current_price:.2f} < $5.00")
            elif current_price < 7.0:
                near_miss_checks.append(f"Price ${current_price:.2f} < $7.00")
                
            # Volume check
            avg_volume = yf_ticker.history(period='1mo')['Volume'].mean()
                
            metrics['volume'] = avg_volume
            if avg_volume < 1_000_000:
                failed_checks.append(f"Volume {avg_volume:,.0f} < 1M")
            elif avg_volume < 1_500_000:
                near_miss_checks.append(f"Volume {avg_volume:,.0f} < 1.5M") 

            # Market Chameleon check - only if we haven't failed already
            if not failed_checks:  # Skip if already failing other checks
                mc_data = self.check_mc_overestimate(ticker)
                win_rate = mc_data['win_rate']
                quarters = mc_data['quarters']
                
                # Store both percentage and quarters in metrics
                metrics['win_rate'] = win_rate
                metrics['win_quarters'] = quarters
                
                # Apply the new threshold of 50%
                if win_rate < 50.0:
                    if win_rate >= 40.0:  # Between 40-50% is now a near miss
                        near_miss_checks.append(f"Winrate {win_rate}% < 50% (over {quarters} earnings)")
                    else:  # Below 40% is still a failure
                        failed_checks.append(f"Winrate {win_rate}% < 40% (over {quarters} earnings)")
            else:
                # Add placeholders if we skip
                metrics['win_rate'] = 0.0
                metrics['win_quarters'] = 0
            
            # IV/RV check
            iv_rv_ratio = analysis.get('iv30_rv30', 0)
            metrics['iv_rv_ratio'] = iv_rv_ratio

            # Use dynamic thresholds based on market conditions
            if iv_rv_ratio < self.iv_rv_near_miss_threshold:
                failed_checks.append(f"IV/RV ratio {iv_rv_ratio:.2f} < {self.iv_rv_near_miss_threshold}")
            elif iv_rv_ratio < self.iv_rv_pass_threshold:
                near_miss_checks.append(f"IV/RV ratio {iv_rv_ratio:.2f} < {self.iv_rv_pass_threshold}")

            # Determine final categorization
            
            # Is this a passing stock (original criteria)?
            is_passing = len(failed_checks) == 0 and len(near_miss_checks) == 0
            
            # Is this a near miss with good term structure?
            is_near_miss_good_term = (len(failed_checks) == 0 and 
                                      len(near_miss_checks) > 0 and 
                                      term_slope <= -0.006)
            
            # Assign tiers:
            # - Tier 1: Original "recommended" stocks (passing all criteria)
            # - Tier 2: Near misses with term structure <= -0.006
            # - Near misses: The rest (term structure must still be <= -0.004)
            if is_passing:
                tier = 1
                metrics['tier'] = 1
                is_tier2 = False
                is_near_miss = False
            elif is_near_miss_good_term:
                tier = 2
                metrics['tier'] = 2
                is_tier2 = True
                is_near_miss = False
            else:
                tier = 0
                metrics['tier'] = 0
                is_tier2 = False
                is_near_miss = len(failed_checks) == 0  # Only a near miss if it only fails non-critical checks

            return {
                'pass': is_passing or is_tier2,  # Both Tier 1 and Tier 2 pass
                'tier': tier,
                'near_miss': is_near_miss,
                'reason': " | ".join(failed_checks) if failed_checks else (
                    " | ".join(near_miss_checks) if near_miss_checks else 
                    "Tier 1 Trade" if is_passing else 
                    "Tier 2 Trade" if is_tier2 else 
                    "Near Miss"
                ),
                'metrics': metrics
            }

        except Exception as e:
            logger.warning(f"Error validating {ticker}: {e}")
            return {
                'pass': False,
                'near_miss': False,
                'metrics': {},
                'reason': f"Validation error: {str(e)}"
            }

    def adjust_thresholds_based_on_spy(self):
        """
        Check SPY's current IV/RV ratio and adjust thresholds if market IV is low.
        If SPY IV/RV <= 1.1, reduce thresholds by 0.1.
        """
        try:
            # Calculate SPY's IV/RV
            spy_analysis = self.analyzer.compute_recommendation('SPY')
            if 'error' not in spy_analysis:
                spy_iv_rv = spy_analysis.get('iv30_rv30', 0)
                logger.info(f"Current SPY IV/RV ratio: {spy_iv_rv:.2f}")
                
                # Three-tiered threshold system based on market conditions
                if spy_iv_rv <= 0.85:  # Extreme low volatility
                    self.iv_rv_pass_threshold = 1.00  # Relaxed by 0.25
                    self.iv_rv_near_miss_threshold = 0.75  # Relaxed by 0.25
                    logger.info(f"Market IV/RV is extremely low ({spy_iv_rv:.2f}). Relaxing IV/RV thresholds by 0.25")
                elif spy_iv_rv <= 1.0:  # Moderately low volatility
                    self.iv_rv_pass_threshold = 1.10  # Relaxed by 0.15
                    self.iv_rv_near_miss_threshold = 0.85  # Relaxed by 0.15
                    logger.info(f"Market IV/RV is low ({spy_iv_rv:.2f}). Relaxing IV/RV thresholds by 0.15")
                else:  # Normal market conditions
                    logger.info(f"Normal market IV/RV ({spy_iv_rv:.2f}). Using standard thresholds")
                
                logger.info(f"Current IV/RV thresholds - Pass: {self.iv_rv_pass_threshold}, Near Miss: {self.iv_rv_near_miss_threshold}")
            else:
                logger.warning(f"Could not calculate SPY IV/RV: {spy_analysis.get('error')}")
                logger.info(f"Using standard IV/RV thresholds - Pass: {self.iv_rv_pass_threshold}, Near Miss: {self.iv_rv_near_miss_threshold}")
        except Exception as e:
            logger.warning(f"Error calculating SPY IV/RV: {e}")
            logger.info(f"Using standard IV/RV thresholds - Pass: {self.iv_rv_pass_threshold}, Near Miss: {self.iv_rv_near_miss_threshold}")
            
    def scan_earnings(self, input_date: Optional[str] = None, workers: int = 0) -> Tuple[List[str], List[Tuple[str, str]], Dict[str, Dict]]:
        self.current_input_date = input_date
        
        # Adjust IV/RV thresholds based on market conditions
        self.adjust_thresholds_based_on_spy()
        
        post_date, pre_date = self.get_scan_dates(input_date)
        
        # Fetch earnings data in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            post_future = executor.submit(self.fetch_earnings_data, post_date)
            pre_future = executor.submit(self.fetch_earnings_data, pre_date)
            post_stocks = post_future.result()
            pre_stocks = pre_future.result()
        
        candidates = []
        # Filter candidates (using list comprehensions for speed)
        candidates = [s for s in post_stocks if s['timing'] == 'Post Market'] + \
                     [s for s in pre_stocks if s['timing'] == 'Pre Market']
        
        logger.info(f"Found {len(candidates)} initial candidates")
        
        recommended = []
        near_misses = []
        stock_metrics = {}
        
        # Process in parallel if workers specified
        if workers > 0:
            # Limit max workers for stability (especially with browser operations)
            effective_workers = min(workers, 8)  # Cap at 8 workers max for stability
            logger.info(f"Using parallel processing with {effective_workers} workers")
            
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                # Submit all stocks for processing
                futures = [executor.submit(self.validate_stock, stock) for stock in candidates]
                
                # Process results as they complete
                with tqdm(total=len(candidates), desc="Analyzing stocks") as pbar:
                    for i, future in enumerate(futures):
                        stock = candidates[i]
                        ticker = stock['ticker']
                        try:
                            result = future.result(timeout=60)  # Add timeout to prevent hanging threads
                            
                            if result['pass']:
                                recommended.append(ticker)
                                stock_metrics[ticker] = result['metrics']
                            elif result['near_miss']:
                                near_misses.append((ticker, result['reason']))
                                stock_metrics[ticker] = result['metrics']
                        except Exception as e:
                            logger.error(f"Error processing {ticker}: {e}")
                        finally:
                            pbar.update(1)
        else:
            # Original batched sequential processing
            batches = [candidates[i:i+self.batch_size] 
                      for i in range(0, len(candidates), self.batch_size)]
            
            with tqdm(total=len(candidates), desc="Analyzing stocks") as pbar:
                for batch in batches:
                    for stock in batch:
                        result = self.validate_stock(stock)
                        ticker = stock['ticker']
                        
                        if result['pass']:
                            recommended.append(ticker)
                            stock_metrics[ticker] = result['metrics']
                        elif result['near_miss']:
                            near_misses.append((ticker, result['reason']))
                            stock_metrics[ticker] = result['metrics']
                        pbar.update(1)
                    
                    if batch != batches[-1]:
                        time.sleep(5)  # Reduced sleep time
        
        return recommended, near_misses, stock_metrics
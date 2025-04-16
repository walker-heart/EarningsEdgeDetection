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
                
    def calculate_iron_fly_strikes(self, ticker: str) -> Dict[str, any]:
        """
        Calculate recommended iron fly strikes based on options closest to 50 delta.
        
        Returns a dictionary containing:
        - short_call_strike: Strike price of the short call (near 50 delta)
        - short_put_strike: Strike price of the short put (near 50 delta)
        - long_call_strike: Strike price of the long call (wing)
        - long_put_strike: Strike price of the long put (wing)
        - short_call_premium: Premium received for short call
        - short_put_premium: Premium received for short put
        - total_credit: Total credit received for the short strikes
        - wing_width: The width used for the wings (3x credit)
        """
        try:
            # Get ticker data
            ticker_obj = yf.Ticker(ticker)
            if not ticker_obj.options or len(ticker_obj.options) == 0:
                return {"error": "No options available"}
            
            # Get the nearest expiration
            expiry = ticker_obj.options[0]
            
            # Get the options chain
            opt_chain = ticker_obj.option_chain(expiry)
            calls = opt_chain.calls
            puts = opt_chain.puts
            
            # Current price
            current_price = ticker_obj.history(period='1d')['Close'].iloc[-1]
            
            # Check if delta column exists
            if 'delta' in calls.columns and 'delta' in puts.columns:
                # Find call closest to 50 delta (absolute value)
                calls['delta_diff'] = abs(abs(calls['delta']) - 0.5)
                closest_call = calls.loc[calls['delta_diff'].idxmin()]
                short_call_strike = closest_call['strike']
                short_call_premium = (closest_call['bid'] + closest_call['ask']) / 2
                
                # Find put closest to 50 delta (absolute value)
                puts['delta_diff'] = abs(abs(puts['delta']) - 0.5)
                closest_put = puts.loc[puts['delta_diff'].idxmin()]
                short_put_strike = closest_put['strike']
                short_put_premium = (closest_put['bid'] + closest_put['ask']) / 2
            else:
                # If delta not available, use strike closest to current price
                # Find call closest to ATM
                calls['price_diff'] = abs(calls['strike'] - current_price)
                closest_call = calls.loc[calls['price_diff'].idxmin()]
                short_call_strike = closest_call['strike']
                short_call_premium = (closest_call['bid'] + closest_call['ask']) / 2
                
                # Find put closest to ATM
                puts['price_diff'] = abs(puts['strike'] - current_price)
                closest_put = puts.loc[puts['price_diff'].idxmin()]
                short_put_strike = closest_put['strike']
                short_put_premium = (closest_put['bid'] + closest_put['ask']) / 2
            
            # Calculate total credit
            total_credit = short_call_premium + short_put_premium
            
            # Calculate wing width - 3x the credit received
            wing_width = 3 * total_credit
            
            # Calculate wing strikes
            long_put_strike = short_put_strike - wing_width
            long_call_strike = short_call_strike + wing_width
            
            # Find actual option strikes that are closest to calculated wings
            available_put_strikes = sorted(puts['strike'].unique())
            available_call_strikes = sorted(calls['strike'].unique())
            
            # Find closest available strikes for wings
            long_put_strike = min(available_put_strikes, key=lambda x: abs(x - long_put_strike))
            long_call_strike = min(available_call_strikes, key=lambda x: abs(x - long_call_strike))
            
            # Find prices for long positions
            long_put_option = puts[puts['strike'] == long_put_strike].iloc[0]
            long_call_option = calls[calls['strike'] == long_call_strike].iloc[0]
            long_put_premium = round((long_put_option['bid'] + long_put_option['ask']) / 2, 2)
            long_call_premium = round((long_call_option['bid'] + long_call_option['ask']) / 2, 2)
            
            # Calculate actual wing widths
            put_wing_width = short_put_strike - long_put_strike
            call_wing_width = long_call_strike - short_call_strike
            
            # Calculate max profit and max risk
            total_debit = long_put_premium + long_call_premium
            net_credit = total_credit - total_debit
            max_profit = net_credit
            max_risk = min(put_wing_width, call_wing_width) - net_credit
            
            # Calculate break-even points
            upper_breakeven = short_call_strike + net_credit
            lower_breakeven = short_put_strike - net_credit
            
            # Calculate risk-reward ratio
            risk_reward_ratio = round(max_risk / max_profit, 1) if max_profit > 0 else float('inf')
            
            # Round values for display
            short_call_strike = round(short_call_strike, 2)
            short_put_strike = round(short_put_strike, 2)
            long_call_strike = round(long_call_strike, 2)
            long_put_strike = round(long_put_strike, 2)
            short_call_premium = round(short_call_premium, 2)
            short_put_premium = round(short_put_premium, 2)
            total_credit = round(total_credit, 2)
            put_wing_width = round(put_wing_width, 2)
            call_wing_width = round(call_wing_width, 2)
            max_profit = round(max_profit, 2)
            max_risk = round(max_risk, 2)
            
            return {
                "short_call_strike": short_call_strike,
                "short_put_strike": short_put_strike,
                "long_call_strike": long_call_strike,
                "long_put_strike": long_put_strike,
                "short_call_premium": short_call_premium,
                "short_put_premium": short_put_premium,
                "long_call_premium": long_call_premium,
                "long_put_premium": long_put_premium,
                "total_credit": round(total_credit, 2),
                "total_debit": round(total_debit, 2),
                "net_credit": round(net_credit, 2),
                "put_wing_width": put_wing_width,
                "call_wing_width": call_wing_width,
                "max_profit": max_profit,
                "max_risk": max_risk,
                "upper_breakeven": round(upper_breakeven, 2),
                "lower_breakeven": round(lower_breakeven, 2),
                "risk_reward_ratio": risk_reward_ratio,
                "expiration": expiry
            }
        except Exception as e:
            logger.warning(f"Error calculating iron fly for {ticker}: {e}")
            return {"error": str(e)}
    
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

    def _get_fallback_earnings_data(self, date: datetime.date) -> List[Dict]:
        """
        Fallback method to get earnings data when the primary source fails.
        Uses Yahoo Finance API as a backup source.
        """
        logger.info(f"Using fallback earnings data source for {date}")
        try:
            import yfinance as yf
            from yahooquery import Screener
            
            # Format date for Yahoo Finance
            formatted_date = date.strftime("%Y-%m-%d")
            
            # Get earnings calendar from yahooquery
            s = Screener()
            calendar = s.get_calendar(formatted_date, formatted_date)
            
            stocks = []
            for entry in calendar['earnings'].get('rows', []):
                try:
                    ticker = entry.get('ticker')
                    if not ticker:
                        continue
                        
                    # Determine timing
                    timing_str = entry.get('startdatetime', '')
                    if timing_str:
                        time_part = timing_str.split('T')[1] if 'T' in timing_str else ''
                        hour = int(time_part.split(':')[0]) if ':' in time_part else 0
                        
                        if hour < 9:  # Before 9 AM
                            timing = 'Pre Market'
                        elif hour >= 16:  # After 4 PM
                            timing = 'Post Market'
                        else:
                            timing = 'During Market'
                    else:
                        timing = 'Unknown'
                    
                    stocks.append({'ticker': ticker, 'timing': timing})
                except Exception as e:
                    logger.debug(f"Error processing calendar entry: {e}")
            
            logger.info(f"Found {len(stocks)} earnings reports from fallback source")
            return stocks
            
        except ImportError:
            logger.warning("yahooquery not installed, using minimal fallback data")
            return []
        except Exception as e:
            logger.warning(f"Error in fallback earnings data: {e}")
            return []
    
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
        
        try:
            # Add a user-agent rotation to avoid blocking
            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
                'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1'
            ]
            import random
            headers['User-Agent'] = random.choice(user_agents)
            
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Try to parse JSON response
            data = response.json()
            
            # Check if data has the expected structure
            if 'data' not in data:
                logger.warning("Invalid response format from Investing.com API")
                return self._get_fallback_earnings_data(date)
                
            soup = BeautifulSoup(data['data'], 'html.parser')
        except (requests.RequestException, ValueError) as e:
            logger.error(f"Error fetching earnings data: {e}")
            return self._get_fallback_earnings_data(date)
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
            # Only perform this check if delta values are available
            call_delta = analysis.get('atm_call_delta')
            put_delta = analysis.get('atm_put_delta')
            
            # Skip this check if either delta is None (not available from Yahoo Finance API)
            if call_delta is not None and put_delta is not None:
                try:
                    # Call delta should be <= 0.57 (not too deep ITM)
                    # Put delta should be >= -0.57 (absolute value <= 0.57)
                    if call_delta > 0.57 or abs(put_delta) > 0.57:
                        return {
                            'pass': False,
                            'near_miss': False,
                            'reason': f"ATM options have delta > 0.57 (call: {call_delta:.2f}, put: {put_delta:.2f})",
                            'metrics': metrics
                        }
                except (TypeError, ValueError):
                    # Skip delta check if we can't process the values
                    logger.debug(f"Skipping delta check for {ticker}: invalid delta values")
            
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
"""
Earnings scanner that handles date logic and filtering.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

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

    def check_mc_overestimate(self, ticker: str) -> float:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--remote-debugging-port=9222')
        options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        
        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            url = f"https://marketchameleon.com/Overview/{ticker}/Earnings/Earnings-Charts/"
            driver.get(url)
            
            wait = WebDriverWait(driver, 20)
            section = wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, "symbol-section-header-descr"))
            )
            
            spans = section.find_elements(By.TAG_NAME, "span")
            for span in spans:
                if "overestimated" in span.text:
                    strong = span.find_element(By.TAG_NAME, "strong")
                    return float(strong.text.strip('%'))
            
            return 0.0
            
        except Exception as e:
            logger.warning(f"Error getting MC data for {ticker}: {e}")
            return 0.0
        finally:
            if driver:
                driver.quit()

    def validate_stock(self, stock: Dict) -> Dict:
        ticker = stock['ticker']
        analysis = None
        failed_checks = []
        near_miss_checks = []
        metrics = {}
        
        try:
            yf_ticker = yf.Ticker(ticker)
            
            # Mandatory check: options availability
            options_dates = yf_ticker.options
            if not yf_ticker.options:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': "No options available",
                    'metrics': {}
                }
                
            metrics['options_expirations'] = len(options_dates)
            metrics['next_expiration'] = options_dates[0] if options_dates else "None"
            
            # Mandatory check: core analysis
            analysis = self.analyzer.compute_recommendation(ticker)
            if "error" in analysis:
                return {
                    'pass': False,
                    'near_miss': False,
                    'reason': f"Analysis error - {analysis['error']}",
                    'metrics': {}
                }
            
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

            # Market Chameleon check
            time.sleep(2)
            mc_pct = self.check_mc_overestimate(ticker)
            metrics['mc_overestimate'] = mc_pct
            if mc_pct < 40.0:  # Changed this to fail if under 40%
                failed_checks.append(f"MC overestimate {mc_pct}% < 40%")
            
            # IV/RV check
            iv_rv_ratio = analysis.get('iv30_rv30', 0)
            metrics['iv_rv_ratio'] = iv_rv_ratio
            metrics['term_structure'] = analysis.get('term_slope', 0)
            if iv_rv_ratio < 1.0:
                failed_checks.append(f"IV/RV ratio {iv_rv_ratio:.2f} < 1.0")
            elif iv_rv_ratio < 1.25:
                near_miss_checks.append(f"IV/RV ratio {iv_rv_ratio:.2f} < 1.25")
            
            # A stock is a near-miss if it has exactly one failure and that failure is in the near-miss range
            is_near_miss = len(failed_checks) == 0 and len(near_miss_checks) == 1

            return {
                'pass': len(failed_checks) == 0 and len(near_miss_checks) == 0,
                'near_miss': len(failed_checks) == 0 and len(near_miss_checks) == 1,
                'reason': " | ".join(failed_checks) if failed_checks else (
                    " | ".join(near_miss_checks) if near_miss_checks else "Passed all criteria"
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

    def scan_earnings(self, input_date: Optional[str] = None) -> Tuple[List[str], List[Tuple[str, str]], Dict[str, Dict]]:
        self.current_input_date = input_date
        post_date, pre_date = self.get_scan_dates(input_date)
        
        post_stocks = self.fetch_earnings_data(post_date)
        pre_stocks = self.fetch_earnings_data(pre_date)
        
        candidates = []
        for stock in post_stocks:
            if stock['timing'] == 'Post Market':
                candidates.append(stock)
        
        for stock in pre_stocks:
            if stock['timing'] == 'Pre Market':
                candidates.append(stock)
        
        logger.info(f"Found {len(candidates)} initial candidates")
        
        recommended = []
        near_misses = []
        stock_metrics = {}
        batches = [candidates[i:i+self.batch_size] 
                  for i in range(0, len(candidates), self.batch_size)]
        
        with tqdm(total=len(candidates), desc="Analyzing stocks") as pbar:
            for batch in batches:
                for stock in batch:
                    result = self.validate_stock(stock)
                    if result['pass']:
                        recommended.append(stock['ticker'])
                        stock_metrics[stock['ticker']] = result['metrics']
                    elif result['near_miss']:
                        near_misses.append((stock['ticker'], result['reason']))
                        stock_metrics[stock['ticker']] = result['metrics']
                    pbar.update(1)
                
                if batch != batches[-1]:
                    time.sleep(15)
        
        return recommended, near_misses, stock_metrics

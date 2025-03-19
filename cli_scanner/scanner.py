#!/usr/bin/env python3
"""
CLI Scanner for earnings-based options opportunities.
Automatically determines dates based on current time and outputs recommended tickers.
"""
 
import argparse
import logging
import sys
import re
from datetime import datetime
 
from utils.logging_utils import setup_logging
from core.scanner import EarningsScanner
 
def main():
    parser = argparse.ArgumentParser(
        description="""
        Scans for recommended options plays based on upcoming earnings.
        If run before 4PM Eastern: Checks today's post-market and tomorrow's pre-market earnings
        If run after 4PM Eastern: Checks tomorrow's post-market and following day's pre-market earnings
        """
    )
    parser.add_argument(
        '--date', '-d',
        help='Optional date to check in MM/DD/YYYY format (e.g., 03/20/2025). '
             'If not provided, uses current date logic.',
        type=str
    )
    args = parser.parse_args()
 
    setup_logging(log_dir="logs")
    logger = logging.getLogger(__name__)
    
    input_date = None
    if args.date:
        try:
            input_date = args.date
            datetime.strptime(input_date, '%m/%d/%Y')  # Validate date format
            logger.info(f"Using provided date: {input_date}")
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            sys.exit(1)
    else:
        now = datetime.now()
        logger.info(f"No date provided. Using current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
 
    scanner = EarningsScanner()
 
    try:
        recommended, near_misses, stock_metrics = scanner.scan_earnings(input_date)
        if recommended or near_misses:
            print("\n=== SCAN RESULTS ===")
            
            print("\nRECOMMENDED STOCKS:")
            if recommended:
                for ticker in recommended:
                    metrics = stock_metrics[ticker]
                    print(f"\n  {ticker}:")
                    print(f"    Price: ${metrics['price']:.2f}")
                    print(f"    Volume: {metrics['volume']:,.0f}")
                    print(f"    MC Overestimate: {metrics['mc_overestimate']:.1f}%")
                    print(f"    IV/RV Ratio: {metrics['iv_rv_ratio']:.2f}")
                    print(f"    Term Structure: {metrics['term_structure']:.3f}")
                    print(f"    Options Expirations: {metrics['options_expirations']}")
                    print(f"    Next Expiration: {metrics['next_expiration']}")
            else:
                print("  None")
 
            print("\nNEAR MISSES:")
            if near_misses:
                for ticker, reason in near_misses:
                    metrics = stock_metrics[ticker]
                    print(f"\n  {ticker}:")
                    print(f"    Failed: {reason}")
                    print(f"    Metrics:")
                    print(f"      Price: ${metrics['price']:.2f}")
                    print(f"      Volume: {metrics['volume']:,.0f}")
                    print(f"      MC Overestimate: {metrics['mc_overestimate']:.1f}%")
                    print(f"      IV/RV Ratio: {metrics['iv_rv_ratio']:.2f}")
                    print(f"      Term Structure: {metrics['term_structure']:.3f}")
                    print(f"      Options Expirations: {metrics['options_expirations']}")
                    print(f"      Next Expiration: {metrics['next_expiration']}")
            else:
                print("  None")
            
            print("\n")
        else:
            logger.info("No recommended stocks found")
    except ValueError as e:
        logger.error(f"Error: {str(e)}")
 
if __name__ == "__main__":
    main()

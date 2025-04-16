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
    parser.add_argument(
        '--parallel', '-p',
        help='Enable parallel processing with specified number of workers',
        type=int,
        default=0
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
        recommended, near_misses, stock_metrics = scanner.scan_earnings(
            input_date=input_date,
            workers=args.parallel
        )
        if recommended or near_misses:
            print("\n=== SCAN RESULTS ===")
            
            print("\nTIER 1 RECOMMENDED TRADES:")
            tier1_tickers = [t for t in recommended if stock_metrics[t].get('tier', 1) == 1]
            if tier1_tickers:
                for ticker in tier1_tickers:
                    metrics = stock_metrics[ticker]
                    print(f"\n  {ticker}:")
                    print(f"    Price: ${metrics['price']:.2f}")
                    print(f"    Volume: {metrics['volume']:,.0f}")
                    print(f"    Expected Move: ${metrics.get('expected_move_dollars', 0):.2f}")
                    print(f"    Winrate: {metrics['win_rate']:.1f}% over the last {metrics['win_quarters']} earnings")
                    print(f"    IV/RV Ratio: {metrics['iv_rv_ratio']:.2f}")
                    print(f"    Term Structure: {metrics['term_structure']:.3f}")
            else:
                print("  None")
            
            print("\nTIER 2 RECOMMENDED TRADES:")
            tier2_tickers = [t for t in recommended if stock_metrics[t].get('tier', 1) == 2]
            if tier2_tickers:
                for ticker in tier2_tickers:
                    metrics = stock_metrics[ticker]
                    print(f"\n  {ticker}:")
                    print(f"    Price: ${metrics['price']:.2f}")
                    print(f"    Volume: {metrics['volume']:,.0f}")
                    print(f"    Expected Move: ${metrics.get('expected_move_dollars', 0):.2f}")
                    print(f"    Winrate: {metrics['win_rate']:.1f}% over the last {metrics['win_quarters']} earnings")
                    print(f"    IV/RV Ratio: {metrics['iv_rv_ratio']:.2f}")
                    print(f"    Term Structure: {metrics['term_structure']:.3f}")
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
                    print(f"      Expected Move: ${metrics.get('expected_move_dollars', 0):.2f}")
                    print(f"      Winrate: {metrics['win_rate']:.1f}% over the last {metrics['win_quarters']} earnings")
                    print(f"      IV/RV Ratio: {metrics['iv_rv_ratio']:.2f}")
                    print(f"      Term Structure: {metrics['term_structure']:.3f}")
            else:
                print("  None")
            
            print("\n")
        else:
            logger.info("No recommended stocks found")
    except ValueError as e:
        logger.error(f"Error: {str(e)}")
 
if __name__ == "__main__":
    main()

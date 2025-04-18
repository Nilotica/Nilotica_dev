import time
import sys
import os
import argparse
import threading
from datetime import datetime
import zmq
import configparser
from typing import Dict, Tuple

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')) # Go up two levels
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import necessary classes and config
try:
    from zmq_services.backtester.simulation_engine import SimulationEngineService
    # We'll run the existing StrategySubscriber, just connecting it to backtest URLs
    from zmq_services.strategy_subscriber import StrategySubscriber
    from zmq_services import config
    from vnpy.trader.constant import Direction, Offset, Status
    # --- 修改导入，移除 plot_performance --- 
    from zmq_services.backtester.performance import calculate_performance, print_performance_report # 移除 plot_performance
    # --- 结束修改 ---
except ImportError as e:
    print(f"Error importing modules: {e}")
    print(f"Project root added to path: {project_root}")
    print(f"Current sys.path: {sys.path}")
    print("Ensure zmq_services/backtester and zmq_services modules exist.")
    sys.exit(1)


# --- Function to run strategy in a separate thread ---
def run_strategy_in_thread(strategy_instance):
    """Target function to run the strategy's start method."""
    print("策略线程: 启动...")
    try:
        # Assuming strategy's start() method contains the main loop
        strategy_instance.start()
    except Exception as e:
        print(f"策略线程运行时发生错误: {e}")
        import traceback
        traceback.print_exc()
    print("策略线程: 已结束。")


# +++ 添加函数：加载产品信息 (与 order_gateway 中类似) +++
def load_product_info(filepath: str) -> Tuple[Dict, Dict]:
    """Loads commission rules and multipliers from an INI file."""
    parser = configparser.ConfigParser()
    if not os.path.exists(filepath):
        print(f"错误：产品信息文件未找到 {filepath}")
        return {}, {}
    try:
        parser.read(filepath, encoding='utf-8')
    except Exception as e:
        print(f"错误：读取产品信息文件 {filepath} 时出错: {e}")
        return {}, {}

    commission_rules = {}
    contract_multipliers = {}
    for symbol in parser.sections():
        if not parser.has_option(symbol, 'multiplier'): continue
        try:
            multiplier = parser.getfloat(symbol, 'multiplier')
            contract_multipliers[symbol] = multiplier
            rule = {
                "open_rate": parser.getfloat(symbol, 'open_rate', fallback=0.0),
                "close_rate": parser.getfloat(symbol, 'close_rate', fallback=0.0),
                "open_fixed": parser.getfloat(symbol, 'open_fixed', fallback=0.0),
                "close_fixed": parser.getfloat(symbol, 'close_fixed', fallback=0.0),
                "min_commission": parser.getfloat(symbol, 'min_commission', fallback=0.0)
            }
            commission_rules[symbol] = rule
        except Exception as e: print(f"警告：处理文件 {filepath} 中 [{symbol}] 时出错: {e}")
    print(f"从 {filepath} 加载了 {len(contract_multipliers)} 个合约的乘数和 {len(commission_rules)} 个合约的手续费规则。")
    return commission_rules, contract_multipliers
# +++ 结束添加 +++


# --- Main Backtest Execution ---
def main():
    parser = argparse.ArgumentParser(description="Run Backtest Simulation")
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime('%Y%m%d'),
        help="Backtest date in YYYYMMDD format (default: today)"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="SimpleStrategy", # Placeholder for potentially selecting different strategies
        help="Name of the strategy class to run (currently uses StrategySubscriber)"
    )
    # Add arguments for strategy parameters if needed
    args = parser.parse_args()

    print(f"--- Backtest Configuration ---")
    print(f"Backtest Date: {args.date}")
    print(f"Strategy: {args.strategy}")
    print(f"Data Source Path: {os.path.abspath(config.BACKTEST_DATA_SOURCE_PATH)}")
    print(f"--- Backtest ZMQ URLs ---")
    print(f"  Market Data PUB: {config.BACKTEST_DATA_PUB_URL}")
    print(f"  Order Report PUB: {config.BACKTEST_ORDER_REPORT_PUB_URL}")
    print(f"  Order Request PULL: {config.BACKTEST_ORDER_REQUEST_PULL_URL}")
    print(f"----------------------------")

    # +++ 加载产品信息 +++
    # 修正路径：从 backtester 目录出发，向上两级到项目根目录，再进入 config
    config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'config')) # <--- 这里需要向上两级
    info_filepath = os.path.join(config_dir, 'project_files', 'product_info.ini')
    print(f"尝试从 {info_filepath} 加载产品信息...")
    commission_rules, contract_multipliers = load_product_info(info_filepath)
    if not commission_rules or not contract_multipliers:
        print("错误：未能加载手续费规则或合约乘数，无法继续回测。")
        return
    # +++ 结束加载 +++

    # 1. Initialize Simulation Engine (传入加载的配置)
    print("初始化模拟引擎...")
    engine = SimulationEngineService(
        data_source_path=config.BACKTEST_DATA_SOURCE_PATH,
        backtest_md_pub_url=config.BACKTEST_DATA_PUB_URL,
        backtest_report_pub_url=config.BACKTEST_ORDER_REPORT_PUB_URL,
        backtest_order_pull_url=config.BACKTEST_ORDER_REQUEST_PULL_URL,
        date_str=args.date,
        commission_rules=commission_rules,         # <--- 传入加载的规则
        contract_multipliers=contract_multipliers, # <--- 传入加载的乘数
        slippage=2.0 
    )
    print("加载回测数据...")
    if not engine.load_data():
        print("错误：未能加载回测数据，无法继续。")
        engine.stop() # Clean up engine resources
        return

    # 2. Initialize Strategy Instance (connecting to BACKTEST URLs)
    print(f"初始化策略: {args.strategy}...")
    # For now, hardcode StrategySubscriber, later could dynamically load strategy class
    if args.strategy == "SimpleStrategy":
        # IMPORTANT: Connect strategy to BACKTEST URLs, not live ones!
        strategy = StrategySubscriber(
            gateway_pub_url=config.BACKTEST_DATA_PUB_URL.replace("*", "localhost"),
            order_req_url=config.BACKTEST_ORDER_REQUEST_PULL_URL.replace("*", "localhost"),
            order_report_url=config.BACKTEST_ORDER_REPORT_PUB_URL.replace("*", "localhost"),
            subscribe_symbols=config.SUBSCRIBE_SYMBOLS # Use symbols from config for now
        )
    else:
        print(f"错误: 未知的策略名称 '{args.strategy}'")
        engine.stop()
        return

    # 3. Start Strategy in a Background Thread
    print("在后台线程中启动策略...")
    strategy_thread = threading.Thread(target=run_strategy_in_thread, args=(strategy,))
    strategy_thread.daemon = True # Allow main program to exit even if strategy thread hangs (optional)
    strategy_thread.start()

    # Give the strategy a moment to initialize and connect sockets
    print("等待策略初始化...")
    time.sleep(2) # Adjust as needed

    # 4. Run Simulation Engine in the Main Thread (this will block)
    print("启动模拟引擎运行循环...")
    engine_stopped_cleanly = False
    try:
        engine.run_simulation() # This runs until data ends or error/interrupt
        engine_stopped_cleanly = True # Mark if simulation completes normally
    except KeyboardInterrupt:
         print("\n主程序检测到 Ctrl+C，正在停止模拟引擎...")
         engine.stop() # Ensure engine stops cleanly
    except Exception as e:
         print(f"模拟引擎运行时发生错误: {e}")
         import traceback
         traceback.print_exc()
         engine.stop()

    # 5. Signal Strategy Thread to Stop (if engine stopped cleanly or errored)
    # If engine stopped, its ZMQ context is terminated, strategy should detect this via ZMQError ETERM
    # However, explicitly calling stop is safer.
    if strategy.running: # Check if strategy is still running
        print("通知策略线程停止...")
        strategy.stop() # Call stop method (only closes sockets now)

    # 6. Wait for Strategy Thread to Finish
    print("等待策略线程结束...")
    strategy_thread.join(timeout=10) # Increased timeout
    if strategy_thread.is_alive():
        print("警告：策略线程在超时后仍在运行。")

    # +++ 在线程结束后终止 ZMQ Context +++
    print("策略线程已结束，终止 ZMQ Context...")
    if strategy.context and not strategy.context.closed:
        try:
            strategy.context.term()
            print("策略 ZMQ Context 已终止。")
        except zmq.ZMQError as e:
            print(f"终止策略 ZMQ Context 时出错: {e}")
    # +++ 结束终止 +++

    # 7. Calculate and Display Backtest Results (传入加载的乘数)
    print("\n--- 回测完成 ---") 
    if strategy:
        all_trades = strategy.trades 
        # --- 调用详细性能计算和打印函数 (传入加载的乘数) ---
        performance_results = calculate_performance(all_trades, contract_multipliers) # <--- 传入加载的乘数
        print_performance_report(performance_results)
    else:
        print("错误：无法获取策略实例以计算性能。")

    print("\n回测流程结束。")


if __name__ == "__main__":
    main()

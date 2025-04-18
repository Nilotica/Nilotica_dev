import time
import sys
import os

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the service class and config
from zmq_services.data_recorder import DataRecorderService
from config import zmq_config as config


def main():
    """Runs the data recorder service."""
    # Get logger instance
    logger = getLogger(__name__)

    logger.info("正在初始化数据记录器...")

    # Get connection URLs and recording path from config
    md_url = config.MARKET_DATA_PUB_URL.replace("*", "localhost")
    report_url = config.ORDER_REPORT_PUB_URL.replace("*", "localhost")
    rec_path = config.DATA_RECORDING_PATH
    # Ensure the path is absolute and uses correct OS separators
    rec_path = os.path.abspath(rec_path)

    recorder = DataRecorderService(md_url, report_url, rec_path)

    logger.info("尝试启动数据记录器...")
    try:
        # The start method contains the main loop
        recorder.start()
    except KeyboardInterrupt:
        logger.info("主程序检测到 Ctrl+C，正在停止...")
        # The recorder's start loop should catch KeyboardInterrupt and call stop
        if recorder.running:
            recorder.stop()
    except Exception as e:
        logger.exception(f"数据记录器运行时发生意外错误: {e}")
        if recorder.running:
            recorder.stop()
    finally:
        logger.info("数据记录器运行结束。")

if __name__ == "__main__":
    # --- Setup Logging ---
    # Add project root first
    project_root_setup = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root_setup not in sys.path:
        sys.path.insert(0, project_root_setup)
    # Now import logger setup
    try:
        from logger import setup_logging, getLogger
        setup_logging(service_name="DataRecorderRunner") # Set service name
    except ImportError as log_err:
        print(f"CRITICAL: Failed to import or setup logger: {log_err}. Exiting.")
        sys.exit(1)

    main()

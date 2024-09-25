import requests
import time
import json
import hashlib
import hmac
import logging
from websocket import create_connection
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Access API keys
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')
# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def gen_sign(event, channel, timestamp, req_param=''):
    message = f"{event}\n{channel}\n{req_param}\n{timestamp}"
    sign = hmac.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()
    logging.debug(f"Generated sign: {sign}")
    return sign

def ws_login(ws):
    timestamp = str(int(time.time()))
    channel = "futures.login"
    event = "api"

    sign = gen_sign(event, channel, timestamp)

    login_payload = {
        "time": int(timestamp),
        "channel": channel,
        "event": event,
        "payload": {
            "req_id": "login-request",
            "api_key": api_key,
            "headers": {},
            "signature": sign,
            "timestamp": timestamp
        }
    }

    try:
        ws.send(json.dumps(login_payload))
        logging.info("Login payload sent.")
        response = ws.recv()
        response_data = json.loads(response)
        if 'data' in response_data and 'errs' not in response_data['data']:
            logging.info("Login successful.")
            return True
        else:
            logging.error(f"Login failed: {response_data}")
            return False
    except Exception as e:
        logging.error(f"Error during login: {e}")
        return False

def create_futures_order_ws(ws, contract, size, price, tif='gtc', stp_act='-', settle='usdt'):
    timestamp = str(int(time.time()))
    channel = 'futures.order_place'
    event = 'api'

    order_payload = {
        "contract": contract,
        "size": size,
        "price": price,
        "tif": tif,
        "stp_act": stp_act,
        "text": "t-my-custom-id",
        "iceberg": 0
    }

    req_param_str = json.dumps(order_payload, separators=(',', ':'))
    sign = gen_sign(event, channel, timestamp, req_param_str)

    message = {
        "time": int(timestamp),
        "channel": channel,
        "event": event,
        "payload": {
            "req_id": "order-request",
            "req_param": order_payload,
            "req_header": {},
            "signature": sign,
            "timestamp": timestamp
        }
    }

    try:
        ws.send(json.dumps(message))
        logging.info(f"Order placement payload sent for {contract}.")
        while True:
            response = ws.recv()
            response_data = json.loads(response)
            if response_data.get("ack") is True:
                logging.info("Order acknowledged.")
            if 'data' in response_data and 'errs' not in response_data['data']:
                logging.info("Order placed successfully.")
                return response_data
            elif 'data' in response_data and 'errs' in response_data['data']:
                error_info = response_data['data']['errs']
                logging.error(f"Error: {error_info['message']} (Type: {error_info['label']})")
                return response_data
            else:
                logging.info("Response:", response_data)
    except Exception as e:
        logging.error(f"Error placing futures order via WebSocket: {e}")
        return None

def monitor_and_trade(contract, trigger_price, order_type):
    ws_url = "wss://fx-ws-testnet.gateio.ws/v4/ws/usdt"
    ws = create_connection(ws_url)

    if not ws_login(ws):
        ws.close()
        return

    in_trade = False

    while True:
        current_price = get_crypto_price(contract)
        if current_price is None:
            time.sleep(5)
            continue

        logging.info(f"Current {contract} price: {current_price}")

        if order_type == 'sell':
            if not in_trade and current_price > trigger_price:
                logging.info(f"Price exceeded {trigger_price}, opening sell order...")
                response = create_futures_order_ws(ws, contract, -1, "0", tif="ioc")
                if response:
                    in_trade = True
                    logging.info("Sell order placed.")
            elif in_trade and current_price < trigger_price:
                logging.info(f"Price dropped below {trigger_price}, closing sell order...")
                response = create_futures_order_ws(ws, contract, 1, "0", tif="ioc")
                if response:
                    in_trade = False
                    logging.info("Sell order closed.")
        
        elif order_type == 'buy':
            if not in_trade and current_price < trigger_price:
                logging.info(f"Price dropped below {trigger_price}, opening buy order...")
                response = create_futures_order_ws(ws, contract, 1, "0", tif="ioc")
                if response:
                    in_trade = True
                    logging.info("Buy order placed.")
            elif in_trade and current_price > trigger_price:
                logging.info(f"Price exceeded {trigger_price}, closing buy order...")
                response = create_futures_order_ws(ws, contract, -1, "0", tif="ioc")
                if response:
                    in_trade = False
                    logging.info("Buy order closed.")

        time.sleep(5)

    ws.close()

def get_crypto_price(contract):
    host = "https://api.gateio.ws"
    prefix = "/api/v4"
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    url = f'{host}{prefix}/futures/usdt/contracts/{contract}'
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        contract_info = response.json()
        return float(contract_info.get("last_price"))
    except requests.exceptions.RequestException as e:
        logging.error(f"Error retrieving price for {contract}: {e}")
        return None

def main():
    currency = input("Enter the currency (BTC/ETH/...): ").strip().upper()
    contract = f"{currency}_USDT"
    
    order_type = input("Enter the order type (buy/sell): ").strip().lower()
    if order_type not in ['buy', 'sell']:
        logging.error("Invalid order type. Exiting...")
        return

    trigger_price = float(input(f"Enter the trigger price for {currency}: ").strip())

    logging.info(f"Monitoring {currency} for {order_type} orders based on trigger price of {trigger_price}...")
    monitor_and_trade(contract, trigger_price, order_type)

if __name__ == "__main__":
    main()

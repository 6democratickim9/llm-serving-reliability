import argparse
import logging
from aiohttp import web
from .server import Config, create_app


def main():
    parser = argparse.ArgumentParser(description="Local non-streaming Ollama gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--upstream", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="llama3.2:1b")
    parser.add_argument("--max-inflight", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--probe-timeout", type=float, default=2)
    args = parser.parse_args()
    config = Config(args.upstream, args.model, args.max_inflight, args.timeout, args.probe_timeout)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    web.run_app(create_app(config), host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()

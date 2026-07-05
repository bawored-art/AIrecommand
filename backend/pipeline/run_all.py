"""python -m pipeline.run_all — collect -> analyze -> rank -> publish 원커맨드 실행.

각 스테이지는 스스로 결과를 메모리에서 전부 구성한 뒤 마지막에만 디스크에 쓰므로,
어느 단계에서 실패하든 그 단계 이전까지의 산출물은 그대로 보존되고 실패한 단계
이후는 아예 실행되지 않는다 (부분 갱신 없음). 실패 시 어느 단계에서 무엇이
잘못됐는지 로그에 남기고 0이 아닌 종료 코드로 끝난다.
"""
import argparse
import logging
import sys

from common.config import load_config
from common.logging_config import setup_logging
from pipeline import analyze, collect, publish, rank

logger = logging.getLogger(__name__)

STAGES = [
    ("collect", collect.run),
    ("analyze", analyze.run),
    ("rank", rank.run),
    ("publish", publish.run),
]


def run(config_path: str = "config.yaml") -> None:
    config = load_config(config_path)
    setup_logging(config["logging"]["dir"], config["logging"]["level"], config["logging"]["retention_days"])

    for name, stage_fn in STAGES:
        logger.info("run_all: [%s] 시작", name)
        try:
            stage_fn(config_path=config_path)
        except Exception:
            logger.exception(
                "run_all: [%s] 단계 실패 — 파이프라인을 중단합니다. 이전 산출물은 그대로 보존됩니다.", name
            )
            raise
        logger.info("run_all: [%s] 완료", name)

    logger.info("run_all: 전체 파이프라인 완료 (collect -> analyze -> rank -> publish)")


def main() -> None:
    parser = argparse.ArgumentParser(description="collect->analyze->rank->publish 전체 파이프라인 실행")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    try:
        run(config_path=args.config)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()

import logging

logger = logging.getLogger("post_sharing")
logger.setLevel(logging.INFO)

handler = logging.FileHandler(f"poast_sharing.log", mode='w')
formatter = logging.Formatter("%(name)s %(asctime)s %(levelname)s %(message)s")

handler.setFormatter(formatter)
logger.addHandler(handler)



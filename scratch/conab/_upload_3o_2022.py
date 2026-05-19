"""Upload the 3o/2022 bulletin which was transiently missing from the main job run.

The Wayback capture of gid 43031 returns OLE2 (d0cf11e0) — likely a Word .doc
rather than a PDF. We upload it as-is with the appropriate content type and
extension so the file is at least preserved in S3.
"""
import ssl, urllib.request, boto3, os

SSL_CTX = ssl.create_default_context()
GID = "43031_158073aea1af4048cdbd8e12898d3eb8"
SNAP = "20220811171826"
BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download"
WB_URL = f"https://web.archive.org/web/{SNAP}if_/{BASE}/{GID}"

MAGIC_MAP = {
    bytes.fromhex("25504446"): ("application/pdf", ".pdf"),
    bytes.fromhex("d0cf11e0"): ("application/msword", ".doc"),
    bytes.fromhex("504b0304"): ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
}

bucket = os.environ["LEVIATHAN_BUCKET"]

print(f"Fetching {WB_URL} ...")
req = urllib.request.Request(WB_URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, context=SSL_CTX, timeout=60) as r:
    data = r.read()

magic4 = data[:4]
content_type, ext = MAGIC_MAP.get(magic4, ("application/octet-stream", ".bin"))
print(f"Got {len(data):,} bytes  magic={magic4.hex()}  detected={content_type}  ext={ext}")

S3_KEY = f"raw/production/source=conab/crop_year=2021_22/survey=03/boletim_cafe_2021_22_03{ext}"

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
s3.put_object(
    Bucket=bucket,
    Key=S3_KEY,
    Body=data,
    ContentType=content_type,
    Metadata={"source_url": WB_URL, "wayback_snap_ts": SNAP, "gid_hash": GID},
)
print(f"Uploaded -> s3://{bucket}/{S3_KEY}")

from __future__ import annotations

from pathlib import Path 

import boto3

def upload_file_to_s3(local_path: str | Path, bucket: str, key: str, aws_region: str = "us-east-1",) -> None:
    path = Path(local_path)

    if not path.exists():
        raise FileNotFoundError(f"Local file does not exist: {path}")
    
    s3 = boto3.client("s3", region_name=aws_region)
    s3.upload_file(str(path), bucket, key)
    


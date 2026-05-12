# package_glue_libs.ps1
# Builds a Python .egg for the leviathan package and uploads it to S3.
# Used by Glue Python Shell jobs via --extra-py-files.
# (Egg format is the documented way to package Python sub-modules for Glue Python Shell.)
#
# Run from the project root:
#   .\scripts\package_glue_libs.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BUCKET = "leviathan-dev-shahem-001"
$EGG_NAME = "leviathan-0.1.0.egg"
$S3_LIB_KEY = "glue-libs/$EGG_NAME"

Write-Host "Building leviathan egg ..."
python scripts/build_glue_egg.py

if (-not (Test-Path $EGG_NAME)) { throw "Egg not found: $EGG_NAME" }

Write-Host "Uploading to s3://$BUCKET/$S3_LIB_KEY ..."
aws s3 cp $EGG_NAME "s3://$BUCKET/$S3_LIB_KEY"

Remove-Item $EGG_NAME
Write-Host "Done. Egg available at s3://$BUCKET/$S3_LIB_KEY"


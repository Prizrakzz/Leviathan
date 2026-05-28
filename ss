[33m13694a77[m[33m ([m[1;36mHEAD[m[33m -> [m[1;32mmain[m[33m, [m[1;31morigin/main[m[33m, [m[1;31morigin/HEAD[m[33m)[m removed deduplication validation due to some commidities having the same regions
[33mb736482c[m more tests
[33m9504b4b3[m Unit tests raw transform
[33mc9b00aab[m fixed R2B nad B2S transform
[33m2b9764b0[m 8 retries with max 300 s wait
[33m19f74c37[m ThreadPoolExecuter
[33m7b348a9c[m infra for silver and bronze
[33mb8c0aa16[m MODIS NDVI batch scripts
[33m29021734[m probe appeears
[33md8993d7f[m silver data verified
[33m1b7cf672[m batch silver job definition
[33m251ce317[m cpc soil silver job
[33m6f2486a2[m fixed failures
[33meb7de018[m unit & module & integration tests
[33m0a506da9[m DoD
[33m12847a4c[m legacy code removed
[33mf454cca4[m  new modules and cleanup
[33mf6e33ef6[m legacy code removal and type checking
[33m19646d0d[m chore: add CPC bronze batch run records (smoke test + 2000-2026 backfill)
[33mb0dd82dd[m batch job fixes
[33m3fff001a[m tf provisioned resources
[33mad537f5d[m cpc soil moisture
[33m4414f064[m Weekly DAG
[33mb6fcaca4[m silver backfill
[33m55427537[m Local Bronze job
[33m2571d13a[m ESR Glue job
[33ma6b4660b[m USDA FAS ESR
[33ma36262b6[m .
[33mf355d75b[m COT data
[33m3393df6f[m .
[33ma7384fed[m fixed gaps in years
[33m447aa528[m wb cmo outlook
[33me80bbcb5[m Pink sheet
[33m88482e73[m yaml for world bank pinksheet
[33m30f3732a[m USDA FGIS Export Inspections
[33m0eb796e5[m fix to make crawl() a generator so it yields each record the instant its landing page is resolved, and have uploads start in parallel immediately
[33mef5cc740[m retries on spot intance
[33m9d671d8f[m DAG
[33mc3500c61[m monthly gain reports
[33me20fa1ab[m more commodity backfillings
[33m58cd4dd7[m More backfills
[33m6d095fef[m Extend WAP Coverage to 1959
[33mb4b332db[m WAP done, GAIN reran again
[33ma5239c3f[m resubmitted WAP
[33m7b5e87c5[m cleanup
[33ma4d3dd2a[m place _discover to scrape the FAS search pagination to collect landing page URLs, then fetch each to get the real PDF URL.
[33me3f7312b[m WAP fix
[33m4146b2dc[m World Agricultural Production
[33mb84bc46d[m backfilling issues fix
[33md0d2f17b[m deduplication done
[33macdceff9[m deduplicating GAIN files
[33mfb0634c1[m Fix Cocoa and OJ Historical Depth
[33m57ec64c3[m fixes
[33m62ca44fd[m GAIN fix
[33m3d47c482[m checked for any gaps in data sources
[33m1e36cfa7[m unica biweekly
[33m433a5db8[m patches
[33mb3da98e6[m SAGIS backfill redo
[33me3afc5f1[m patched bugs
[33mfee06a89[m WASDE
[33m9eba82c6[m usda nass citrus
[33m97edc057[m stale references
[33m4c4817a0[m replacing Playwright with Wayback CDX discovery, adding a download_url field
[33mc4362e6c[m AMS cotton annual
[33m33d39d00[m added Soybean meal and FCOJ batch jobs
[33m4292a6a5[m parallelized fargate batch jobs
[33m2440b8f2[m All USDA GAINS commodities
[33m00b6e164[m web crawling
[33me12d2f3b[m gain coffee data
[33m56e57a0e[m ECR and Batch infra code
[33mf4feaeea[m sagis cec
[33m94c40832[m few fixes
[33mb7edec86[m sagis weekly excel
[33md21a91d2[m sagis data
[33mc2180670[m headers are uppercase
[33m6edfefc0[m USDA NASS
[33m1de0cf7e[m PSD data
[33m7d7d2fa5[m MPOC
[33mfc6ec715[m MPOB pdfs
[33m7d541abb[m MPOB data
[33ma9026744[m backfilled missing data
[33mdc1d1524[m filled gaps in CONAB data
[33m59750c70[m harvest_year
[33m146ae773[m Enumerate missing UNICA bi-weekly bulletin IDs
[33m46c5b3ed[m added playwright again to scrape missing years and bi-weekly reports.
[33md2c87959[m no need for playwright
[33m5cbb9a8d[m UNICA ingested
[33m94aa8f0c[m cleanup part 2
[33md3539eb5[m cleanup part 1
[33m87966b36[m added FNC Columbia
[33me15f8180[m reorganized conab data
[33ma42db091[m 2022_23 through 2025_26
[33m8033a44d[m Conab URL patterns
[33me3dc9cff[m fixes
[33m2dfbdcba[m ingesting WMT data
[33m32decad2[m added CONAB pdf data source for arabica coffee
[33m43e63d5c[m smth
[33m7d067e53[m data quality checks at each layer
[33m923453eb[m cleanup
[33m4aabe287[m B2S batch jobs
[33ma7bb07a9[m fixed docker
[33m76cd9863[m some fixes
[33m12bf2568[m used batch for ingestion to bronze and implemented budget alert and lifecycle rules
[33mb5740afd[m fixed some scripts
[33mfe4a2e71[m fixed the number of concurrency on glue python shell jobs
[33md9cce9b2[m implemented multi-threading before the full backfill
[33m2d82987f[m CHIRPS infra
[33m78e35d3a[m added CHIRPS rainfall data
[33m5f328172[m cleaned code and removed circular dependency
[33mc0f68a2a[m added unit tests
[33m2e58770c[m standardized silver schema, schema validation in ingestion, retry logic, reusable glue tf modules and base jobs
[33mcec53740[m airflow glow jobs for all 31 commodities
[33m3b57ff72[m cleanup: DRY, types, dead code, configs for all 31 commodities
[33ma1f4b063[m backfill for all commodities
[33meb03d3d2[m added the production yield of all other commodities, rewrote the documentation
[33m4b5abfa1[m added permissions to the orchestrator and
[33ma0475eed[m added Airflow DAG orchestrater
[33m60557b66[m commodity var
[33m306ba2b0[m added new locations for all soft, grain and oilseed commodities and made sure all infra codes are reusable components
[33m1189e14a[m fixed hardcoded terraform variable
[33m4ae77783[m rewrote the readme
[33mcf206e9e[m fixed IAM permissions and glue jobs
[33m18514880[m added athen for validation scripts and cloudwatch alarms to monitor logs and costs
[33mf96457ad[m standardized commodity country name and parameterized commodity names. implemented multithreading and parallel processing
[33mafdddccd[m added glue jobs raw -> bronze, bronze -silver
[33m827bee2a[m added AWS batch + docker
[33mce4e2713[m added production quantity
[33m08bcec68[m brought back flag column
[33m91484c0a[m backfilling done
[33m3145636c[m updated scripts to backfill weather data
[33mdf0a2a26[m uploaded normalized cocoa data
[33m967b99f7[m transform script of production yield data
[33md5a5dc29[m added production data
[33me4e95665[m terraform vars
[33m1eb4aec4[m S3 Iac Terraform
[33m053a2df7[m nasa power ingestion job
[33mf41964a7[m added s3 py file
[33m019c8d72[m added logging and yaml parser
[33m55394f31[m added configs
[33me654a553[m env added
[33me0bc1209[m folder restructuring
[33mc2803079[m new banner
[33m51323754[m new banner
[33m4c7d0937[m changed banner
[33m7d0b3097[m fixing readme banner
[33m6ecb942c[m Set up Leviathan project structure and README banner
[33m9596d85a[m Add banner image to README
[33m40c0862e[m Initial commit

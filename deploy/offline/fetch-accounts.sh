#!/usr/bin/env bash
# Receive the encrypted account configuration on the deployment host.
set -euo pipefail
umask 077
if [[ $# != 1 || -z $1 ]]; then echo 'Usage: bash fetch-accounts.sh NEW_PRIVATE_DIRECTORY' >&2; exit 2; fi
dest=$1
if [[ -e $dest || -L $dest ]]; then echo 'Choose a new directory for the private configuration.' >&2; exit 2; fi
repo=BilibiliSZdaomei/easphub-plan-review
workflow=provision-accounts.yml
for tool in gh openssl base64 mktemp; do command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 1; }; done
parent=$(dirname -- "$dest")
[[ -d $parent ]] || { echo 'Parent directory must already exist.' >&2; exit 2; }
work=$(mktemp -d -- "$parent/.plan-review-provision.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
mkdir -m 700 -- "$work/incoming" "$work/result"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$work/recipient.pem" 2>/dev/null
public_key=$(openssl pkey -in "$work/recipient.pem" -pubout -outform DER | base64 -w0)
request_id=$(openssl rand -hex 16)
gh workflow run "$workflow" --repo "$repo" --ref main -f request_id="$request_id" -f public_key="$public_key" >/dev/null
run_id=''
for _ in {1..60}; do
  run_id=$(gh api -X GET "repos/$repo/actions/workflows/$workflow/runs" -f event=workflow_dispatch -f branch=main -f per_page=100 --jq ".workflow_runs[] | select(.display_title == \"Account delivery $request_id\") | .id")
  [[ -n $run_id ]] && break
  sleep 2
done
[[ $run_id =~ ^[0-9]+$ ]] || { echo 'Could not locate the requested delivery in GitHub Actions.' >&2; exit 1; }
# Poll with the ordinary workflow-runs API so fine-grained tokens do not require checks:read.
for _ in {1..180}; do
  state=$(gh api "repos/$repo/actions/runs/$run_id" --jq '.status + ":" + (.conclusion // "")')
  [[ $state == completed:* ]] && break
  sleep 5
done
[[ $state == completed:success ]] || { echo "GitHub account delivery did not complete (run $run_id)." >&2; exit 1; }
gh run download "$run_id" --repo "$repo" --name "provision-$request_id" --dir "$work/incoming"
openssl pkeyutl -decrypt -inkey "$work/recipient.pem" -in "$work/incoming/key.wrapped" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256 -out "$work/result/accounts.key"
mv -- "$work/incoming/accounts.easphub" "$work/result/accounts.easphub"
chmod 600 -- "$work/result/accounts.key" "$work/result/accounts.easphub"
# Claim the final directory exclusively; an existing configuration is never overwritten.
mkdir -m 700 -- "$dest"
mv -- "$work/result/accounts.key" "$work/result/accounts.easphub" "$dest/"
printf 'Account configuration received in %s\n' "$dest"

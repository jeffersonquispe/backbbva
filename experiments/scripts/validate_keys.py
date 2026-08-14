import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)
from dotenv_util import parse_dotenv

parse_dotenv(os.path.join(_ROOT_DIR, '.env'), override=True)

print("AWS_ACCESS_KEY_ID:", os.environ.get('AWS_ACCESS_KEY_ID'))
print("AWS_SECRET_ACCESS_KEY:", "SET (" + str(len(os.environ.get('AWS_SECRET_ACCESS_KEY', ''))) + " chars)" if os.environ.get('AWS_SECRET_ACCESS_KEY') else "NOT SET")
print("AWS_DEFAULT_REGION:", os.environ.get('AWS_DEFAULT_REGION'))

try:
    import boto3
except ImportError:
    print("Installing boto3...")
    os.system("pip install boto3 python-dotenv")
    import boto3

ak = os.environ.get('AWS_ACCESS_KEY_ID')
sk = os.environ.get('AWS_SECRET_ACCESS_KEY')

print("\n--- 1. Testing STS (Caller Identity) ---")
try:
    sts = boto3.client('sts', aws_access_key_id=ak, aws_secret_access_key=sk, region_name='us-east-1')
    identity = sts.get_caller_identity()
    print("✅ STS Auth Success!")
    print(f"Account: {identity.get('Account')}")
    print(f"ARN: {identity.get('Arn')}")
    print(f"UserId: {identity.get('UserId')}")
except Exception as e:
    print("❌ STS Auth Failed:", e)

print("\n--- 2. Testing Bedrock Anthropic Models in us-east-1 & us-west-2 ---")
for region in ['us-east-1', 'us-west-2', 'us-east-2', 'eu-west-1']:
    try:
        bedrock = boto3.client('bedrock', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=region)
        models = bedrock.list_foundation_models(byProvider='Anthropic')
        anthropic_models = [m['modelId'] for m in models.get('modelSummaries', [])]
        print(f"✅ Bedrock [{region}]: Found {len(anthropic_models)} Anthropic models:")
        for m_id in anthropic_models:
            print(f"   - {m_id}")
    except Exception as e:
        print(f"❌ Bedrock [{region}] Error: {e}")

print("\n--- 3. Testing Bedrock Runtime Call (Inference Test) ---")
import json
for region in ['us-east-1', 'us-west-2']:
    try:
        runtime = boto3.client('bedrock-runtime', aws_access_key_id=ak, aws_secret_access_key=sk, region_name=region)
        model_candidates = [
            'anthropic.claude-sonnet-4-6',
            'us.anthropic.claude-sonnet-4-6',
            'anthropic.claude-sonnet-4-20250514-v1:0',
            'anthropic.claude-3-haiku-20240307-v1:0'
        ]
        for model_id in model_candidates:
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 50,
                    "messages": [{"role": "user", "content": "Hola ARIA"}]
                })
                res = runtime.invoke_model(modelId=model_id, body=body)
                res_body = json.loads(res['body'].read())
                reply = res_body['content'][0]['text']
                print(f"✅ Bedrock Runtime [{region}] [{model_id}] Response: {reply}")
                break
            except Exception as e_mod:
                print(f"⚠️ Bedrock Runtime [{region}] [{model_id}] failed: {e_mod}")
    except Exception as e:
        print(f"❌ Bedrock Runtime [{region}] client failed: {e}")


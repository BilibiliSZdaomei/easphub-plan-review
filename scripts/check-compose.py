"""Native Compose config validation only; never starts, stops or builds services."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from artifact_paths import artifact_root

ROOT=Path(__file__).resolve().parents[1]
APP_ID='plan-review'
# A verified real base image supplies the required image field during parsing.
# This is NOT an application image, is never run here, and is not a release default.
PARSER_IMAGE='python:3.12.13-slim-bookworm@sha256:6e13e65c55e33adf203d77ee371cf8bf5d81bd4902ef07565721f46bf44917af'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose',required=True,help='Path to the standalone Compose executable')
    args=parser.parse_args()
    executable=str(Path(args.compose).resolve())
    version=subprocess.check_output([executable,'version','--short'],text=True,encoding='utf-8').strip()
    work=artifact_root(ROOT, APP_ID)
    work.mkdir(parents=True, exist_ok=True)
    evidence=[]
    with tempfile.TemporaryDirectory(prefix='compose-parse-',dir=work) as directory:
        root=Path(directory)
        for target in ('home','company'):
            environment=dict(os.environ)
            environment.update(APP_IMAGE=PARSER_IMAGE,TZ='Europe/Budapest',APP_DATA_HOST_PATH=str(root/target/'data'),MYSQL_DATA_HOST_PATH=str(root/target/'mysqldata'))
            # These files contain only synthetic values and are never used by a server.
            for key in ('DATABASE_PASSWORD_FILE','DATABASE_ROOT_PASSWORD_FILE','MYSQL_CLIENT_FILE','SESSION_TOKEN_FILE'):
                path=root/(target+'-'+key)
                path.write_text('synthetic-config-parsing-only',encoding='utf-8')
                environment[key]=str(path)
            command=[executable,'--profile','operations','--env-file',str(ROOT/'deploy'/('.env.'+target+'.example')),'-f',str(ROOT/'deploy'/('compose.'+target+'.yml')),'config','--format','json']
            result=subprocess.run(command,env=environment,capture_output=True,text=True,encoding='utf-8',check=True)
            model=json.loads(result.stdout)
            assert model['name']=='easphub-'+APP_ID+'-'+target
            web=model['services']['web']
            assert APP_ID+'-'+target+'-web' in web['networks']['proxy-net']['aliases']
            assert model['networks']['proxy-net']['external']
            for name,service in model['services'].items():
                assert service['platform']=='linux/amd64'
                assert not service.get('ports') and not service.get('container_name')
                assert service['read_only'] and 'ALL' in service['cap_drop']
                assert 'no-new-privileges:true' in service['security_opt']
                assert float(service['mem_limit'])>0 and float(service['cpus'])>0 and int(service['pids_limit'])>0
                assert service['logging']['options']=={'max-size':'20m','max-file':'5'}
                if name!='database':
                    assert service['user']=='10001:10001'
                    assert service['environment']['DEPLOY_ENV']==target
                else:
                    assert 'proxy-net' not in service['networks']
                    assert model['networks']['app-private']['internal']
            if APP_ID=='plan-review':
                assert model['services']['migrate']['profiles']==['operations']
                assert 'migrate' not in web.get('depends_on',{})
                assert 'SELECT 1' in ' '.join(model['services']['database']['healthcheck']['test'])
            environment.pop('APP_IMAGE')
            missing=subprocess.run(command,env=environment,capture_output=True,text=True,encoding='utf-8')
            assert missing.returncode!=0 and 'APP_IMAGE' in missing.stderr
            evidence.append({'environment':target,'native_config':'PASS','missing_required_image_refused':'PASS','services':list(model['services'])})
    report={'status':'PASS','compose_version':version,'parse_only':True,'image_for_parse_only':PARSER_IMAGE,'application_image_built':False,'results':evidence}
    path=work/'compose-tests.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()

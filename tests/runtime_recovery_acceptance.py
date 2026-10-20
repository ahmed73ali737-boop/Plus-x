"""P02: five cycles/scenario on a newly named, disposable Compose project only.

Recovery deadline is fixed BEFORE measurement. Never restarts the proxy. Forces
an app IP change by reserving its previous address in a temporary container.
"""
from pathlib import Path
import ipaddress, json, os, secrets, subprocess, sys, time, uuid
import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'qa/runtime-recovery'
DEADLINE=90
CYCLES=5


def recovery_subnet(existing):
    occupied=[ipaddress.ip_network(config['Subnet']) for network in existing
              for config in ((network.get('IPAM') or {}).get('Config') or []) if config.get('Subnet')]
    available=[ipaddress.ip_network(f'10.233.{index}.0/24') for index in range(256)]
    available=[network for network in available if not any(network.overlaps(other) for other in occupied if other.version==4)]
    if not available:raise RuntimeError('NO_ISOLATED_RECOVERY_SUBNET')
    return str(secrets.choice(available))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    project='px-recovery-'+uuid.uuid4().hex[:10]
    env={**os.environ,'RECOVERY_DB_PASSWORD':secrets.token_hex(24),
         'PULSEX_SOURCE_SHA':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    command=['docker','compose','-p',project,'-f',str(ROOT/'ops/compose.recovery.yaml')]
    report={'status':'failed','source_sha':env['PULSEX_SOURCE_SHA'],'project':project,
            'deadline_seconds':DEADLINE,'cycles_per_scenario':CYCLES,'cycles':[]}
    blocker=None
    last_readiness={}
    def run(*args,timeout=300):
        try:
            return subprocess.check_output([*command,*args],cwd=ROOT,env=env,text=True,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.CalledProcessError as error:
            (OUT/'command-failure.log').write_text((error.output or '').replace(env['RECOVERY_DB_PASSWORD'],'[redacted]'),encoding='utf-8')
            raise
    def cid(service):return run('ps','-q',service).strip()
    def inspect(container):return json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
    def snapshot():
        return {service:{'id':cid(service),'state':inspect(cid(service))['State']['Status'],
                        'networks':{k:v['IPAddress'] for k,v in inspect(cid(service))['NetworkSettings']['Networks'].items()}}
                for service in ('app','postgres','proxy')}
    with httpx.Client(base_url='http://127.0.0.1:18080',trust_env=False,timeout=4) as client:
        def wait_ready(start=None):
            start=time.monotonic() if start is None else start
            while time.monotonic()-start<DEADLINE:
                try:
                    responses=[client.get(base+'/api/health/ready') for base in ('http://127.0.0.1:14310','http://127.0.0.1:18080')]
                    last_readiness.update({key:{'status':r.status_code,'body':r.text[:1000]} for key,r in zip(('direct','proxy'),responses)})
                    if all(r.status_code==200 for r in responses):
                        return round(time.monotonic()-start,3)
                except httpx.HTTPError:pass
                time.sleep(.5)
            raise RuntimeError('RECOVERY_DEADLINE_EXCEEDED')
        try:
            network_ids=subprocess.check_output(['docker','network','ls','-q'],text=True).split()
            existing=json.loads(subprocess.check_output(['docker','network','inspect',*network_ids],text=True)) if network_ids else []
            env['RECOVERY_SUBNET']=recovery_subnet(existing)
            report['subnet']=env['RECOVERY_SUBNET']
            run('up','-d','--build',timeout=900)
            wait_ready()
            run('exec','-T','proxy','caddy','validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile')
            proxy_id=cid('proxy')
            accounts=json.loads(run('exec','-T','app','cat','/app/data/recovery-accounts.json'))
            admin=next(x for x in accounts if x['email']=='organizer@pulsex.test')
            auth=client.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']});auth.raise_for_status()
            client.headers.update({'X-CSRF':auth.json()['csrf'],'Origin':'http://127.0.0.1:18080'})
            guest=client.post('/api/public/events/demo/guests/register',json={'name':'Recovery sentinel','phone':'+967777993001','consent':True});guest.raise_for_status()
            payload={'guest_number':guest.json()['guest_number'],'scan_id':str(uuid.uuid4()),'mode':'entry','checkpoint':'main','quantity':1}
            endpoint='/api/admin/events/event-demo/guest-checkins'
            first=client.post(endpoint,json=payload);first.raise_for_status();assert first.json()['status']=='accepted'
            totals=client.get(endpoint).json()
            for scenario in ('app-stop-start','app-recreate-new-ip','database-outage'):
                for index in range(CYCLES):
                    cycle={'scenario':scenario,'cycle':index+1,'before':snapshot(),'status':'failed'}
                    report['cycles'].append(cycle)
                    started=time.monotonic()
                    if scenario=='app-stop-start':
                        app_id=cid('app')
                        run('stop','-t','30','app')
                        # Start the exact stopped container. Compose's service
                        # convergence is exercised separately by the recreate case.
                        subprocess.check_output(['docker','start',app_id],text=True,timeout=30)
                        assert cid('app')==app_id,'STOP_START_CHANGED_CONTAINER'
                    elif scenario=='app-recreate-new-ip':
                        old=inspect(cid('app'));network,net=next(iter(old['NetworkSettings']['Networks'].items()))
                        run('stop','app');run('rm','-f','app')
                        blocker=project+'-reserve'
                        image=inspect(proxy_id)['Config']['Image']
                        subprocess.check_output(['docker','run','-d','--name',blocker,'--network',network,'--ip',net['IPAddress'],'--entrypoint','sleep',image,'180'],text=True)
                        run('up','-d','--no-deps','app')
                        assert next(iter(inspect(cid('app'))['NetworkSettings']['Networks'].values()))['IPAddress']!=net['IPAddress']
                    else:
                        run('stop','-t','30','postgres')
                        assert client.get('http://127.0.0.1:14310/api/health/live').status_code==200
                        assert client.get('http://127.0.0.1:14310/api/health/ready').status_code==503
                        assert client.get('/api/health/ready').status_code==503
                        run('start','postgres')
                    cycle['recovery_seconds']=wait_ready(started)
                    assert cid('proxy')==proxy_id,'PROXY_WAS_RESTARTED'
                    replay=client.post(endpoint,json=payload);replay.raise_for_status();assert replay.json()['status']=='duplicate'
                    current=client.get(endpoint).json()
                    for key in ('total_checkins','inside_count','admitted_people'):assert current[key]==totals[key],key
                    cycle.update(status='passed',after=snapshot(),sentinel_and_replay_unchanged=True)
                    if blocker:subprocess.run(['docker','rm','-f',blocker],check=True,capture_output=True);blocker=None
            report['status']='passed'
        except Exception as error:
            report['error']=str(error).replace(env['RECOVERY_DB_PASSWORD'],'[redacted]')
            report['last_readiness']=last_readiness
            try:
                report['failure_containers']=snapshot()
                activity=run('exec','-T','postgres','psql','-U','pulsex','-d','pulsex','-Atc',
                    'SELECT state, wait_event_type, wait_event FROM pg_stat_activity WHERE datname = current_database()')
                report['database_wait_states']=activity.splitlines()
            except Exception:pass
        finally:
            try:
                logs=run('logs','--no-color').replace(env['RECOVERY_DB_PASSWORD'],'[redacted]')
                (OUT/'containers.log').write_text(logs,encoding='utf-8')
            except Exception:pass
            if blocker:subprocess.run(['docker','rm','-f',blocker],capture_output=True)
            try:run('down','--volumes','--remove-orphans')
            except Exception as error:report.update(status='failed',cleanup_error=type(error).__name__)
            (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())

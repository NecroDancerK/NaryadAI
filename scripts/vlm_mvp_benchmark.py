"""Evaluate the MVP observation client; human grading is explicit, never inferred."""
import argparse
import asyncio
import base64
import hashlib
import html
import json
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def experiment_prompt(default_prompt,default_version,path=None,version=None):
    if (path is None)!=(version is None):
        raise ValueError('Specify both --prompt-file and --prompt-version')
    if path is None:
        return default_prompt,default_version
    if not re.fullmatch(r'experiment-[a-z0-9-]{1,60}',version):
        raise ValueError('Experimental prompt version must start with experiment-')
    if path.stat().st_size>8192:
        raise ValueError('Experimental prompt is too large')
    prompt=path.read_text(encoding='utf-8').strip()
    if not prompt:
        raise ValueError('Experimental prompt must not be empty')
    return prompt,version


def compare_reports(baseline,candidate):
    for key in ['model','model_sha256','mmproj_sha256','client_source_sha256','manifest_sha256','parameters']:
        if baseline.get(key)!=candidate.get(key) or key not in baseline:
            raise ValueError(f'Comparison changes more than the prompt: {key}')
    if baseline['prompt_sha256']==candidate['prompt_sha256']:
        raise ValueError('Comparison requires different prompts')
    left={row['id']:row for row in baseline['results']}
    right={row['id']:row for row in candidate['results']}
    if len(left)!=len(baseline['results']) or len(right)!=len(candidate['results']) or not left or left.keys()!=right.keys():
        raise ValueError('Comparison cases must match exactly')
    for key,row in left.items():
        if row['image_sha256']!=right[key]['image_sha256']:
            raise ValueError('Comparison images must match exactly')
    def diagnostic(report):
        terms=re.compile(r'разруш|облом|поврежд|дефект|износ|замен|удал|утеч|масл',re.I)
        successful=[row for row in report['results'] if row['status']=='ok']
        return {'ok':len(successful),'errors':len(report['results'])-len(successful),
                'observation_vocabulary_cases':sum(bool(terms.search(' '.join(row['result']['observations']))) for row in successful),
                'empty_observations':sum(not row['result']['observations'] for row in successful),
                'median_seconds':statistics.median(row['seconds'] for row in successful) if successful else None,
                'observed_total_gpu_max_mib':report['gpu'].get('observed_total_max_mib')}
    return {'baseline_sha256':fingerprint(baseline),'candidate_sha256':fingerprint(candidate),
            'changed_variable':'system_prompt','baseline':diagnostic(baseline),'candidate':diagnostic(candidate),
            'quality_score':None,
            'warning':'Vocabulary counts are not hallucination/error rates; negations and true findings also match. Human review required. Timing is exploratory, not a controlled performance benchmark.'}


def samples_from(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    samples = manifest.get('samples', [])
    if not 1 <= len(samples) <= 100:
        raise ValueError('Need 1..100 samples')
    checked, seen = [], set()
    for sample in samples:
        relative = Path(sample['file'])
        path = (manifest_path.parent / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError('Image must be inside manifest directory')
        if sample['file'] in seen or not path.is_file() or path.stat().st_size > 10*1024*1024:
            raise ValueError('Duplicate, missing or oversized image')
        if digest(path) != sample.get('sha256'):
            raise ValueError('Image SHA256 does not match manifest')
        seen.add(sample['file'])
        checked.append((sample,path))
    return manifest,checked


def summary(results):
    successes = [row for row in results if row['status']=='ok']
    times = sorted(row['seconds'] for row in successes)
    return {'samples':len(results),'normalized_valid_results':len(successes),
            'errors':len(results)-len(successes),
            'median_success_seconds':statistics.median(times) if times else None,
            'max_success_seconds':max(times) if times else None,
            'quality_score':None,'quality_note':'Requires human review; schema success is not visual accuracy'}


def review_template(report):
    return {'report_sha256':fingerprint(report),'reviewer':'','cases':[
        {'id':row['id'],'grounding':None,'hallucinated_detail':None,
         'unsupported_safety_or_repair_claim':None,'appropriate_uncertainty':None,'note':''}
        for row in report['results'] if row['status']=='ok']}


def summarize_review(report,review):
    if review.get('report_sha256') != fingerprint(report):
        raise ValueError('Review belongs to a different report')
    if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip():
        raise ValueError('Specify a human reviewer')
    expected = {row['id'] for row in report['results'] if row['status']=='ok'}
    cases = review.get('cases',[])
    if len(cases)!=len(expected) or {row['id'] for row in cases}!=expected:
        raise ValueError('Review cases must match successful results exactly')
    judged = []
    for row in cases:
        if row.get('grounding') is None:
            continue
        if row['grounding'] not in {'grounded','partly_grounded','ungrounded','cannot_judge'}:
            raise ValueError('Invalid grounding grade')
        if row['grounding']=='cannot_judge':
            continue
        for key in ['hallucinated_detail','unsupported_safety_or_repair_claim','appropriate_uncertainty']:
            if type(row.get(key)) is not bool:
                raise ValueError('Judged cases require boolean grades')
        judged.append(row)
    return {'successful_cases':len(expected),'judged_cases':len(judged),
            'unjudged_or_cannot_judge':len(expected)-len(judged),
            'fully_grounded_cases':sum(row['grounding']=='grounded' for row in judged),
            'hallucinated_detail_cases':sum(row['hallucinated_detail'] for row in judged),
            'unsupported_claim_cases':sum(row['unsupported_safety_or_repair_claim'] for row in judged),
            'appropriate_uncertainty_cases':sum(row['appropriate_uncertainty'] for row in judged),
            'warning':'Small exploratory sample; no production accuracy or repair approval claim'}


def render_report(report,manifest_path):
    _,samples=samples_from(manifest_path.resolve())
    paths={sample['sha256']:path for sample,path in samples}
    cards=[]
    for row in report['results']:
        if row['image_sha256'] not in paths:
            raise ValueError('Report image does not match dataset')
        data=paths[row['image_sha256']].read_bytes()
        mime='image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None
        image=f'<img alt="Sample {html.escape(str(row["id"]),quote=True)}" src="data:{mime};base64,{base64.b64encode(data).decode()}">' if mime else '<p>Unsupported image</p>'
        body=html.escape(json.dumps({'reference':row['reference'],'answer':row.get('result'),'error':row.get('error')},ensure_ascii=False,indent=2))
        cards.append(f'<article><h2>Sample {html.escape(str(row["id"]))}</h2>{image}<pre>{body}</pre></article>')
    metadata=html.escape(json.dumps({'model':report['model'],'prompt_version':report['prompt_version'],'dataset':report['dataset'],'summary':report['summary'],'gpu':{key:value for key,value in report['gpu'].items() if key!='samples'}},ensure_ascii=False,indent=2))
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qwen3-VL — проверка MVP</title><style>body{font:16px system-ui;background:#10251e;color:#e5eee8;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}article{padding:16px;background:#20352a;border-radius:12px}img{width:100%;max-height:380px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}</style><h1>Qwen3-VL: ответы MVP-клиента</h1><p>Исследовательская проба, не точность на реальном оборудовании и не приёмка ремонта. Сопоставьте каждое наблюдение с фото; review.json заполняет человек. Метки набора не были переданы модели. Ответы нормализованы приложением: needs_human_review принудительно true, отсутствующее ограничение может добавлять клиент.</p><p>Отчёт содержит копии фото: не публикуйте частные производственные изображения.</p><pre>'+metadata+'</pre><main>'+''.join(cards)+'</main></html>'


async def run(args):
    # Imported only for inference: helpers/tests use the standard library.
    import httpx
    from app import vision
    from app.config import settings
    if urlparse(args.url).hostname not in {'127.0.0.1','localhost','::1'} or urlparse(args.url).scheme != 'http' or urlparse(args.url).username:
        raise ValueError('Only a loopback HTTP inference server is allowed')
    manifest,samples = samples_from(args.manifest.resolve())
    prompt,prompt_version=experiment_prompt(vision.PROMPT,vision.PROMPT_VERSION,args.prompt_file,args.prompt_version)
    args.output.mkdir(parents=True,exist_ok=False)
    settings.vlm_base_url = args.url
    settings.vlm_model = 'NaryadAI-Qwen3-VL-4B'
    settings.vlm_timeout_seconds = 90
    async with httpx.AsyncClient(base_url=args.url,timeout=10) as client:
        key = settings.vlm_api_key.get_secret_value() if settings.vlm_api_key else ''
        response = await client.get('/v1/models',headers={'Authorization':f'Bearer {key}'} if key else {})
        response.raise_for_status()
        models=response.json()
    if not any(row['id']==settings.vlm_model for row in models.get('data',[])):
        raise ValueError('Start the chosen Qwen3-VL server with the MVP alias')
    gpu,stop = [],threading.Event()
    def monitor():
        while not stop.is_set():
            try:
                result=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,check=True)
                gpu.append(int(result.stdout.strip().splitlines()[0]))
            except (OSError,ValueError,subprocess.SubprocessError):
                pass
            stop.wait(0.5)
    thread=threading.Thread(target=monitor,daemon=True)
    thread.start()
    rows=[]
    original_prompt=vision.PROMPT
    vision.PROMPT=prompt  # This CLI process only; no backend files/configuration change.
    try:
        for index,(sample,path) in enumerate(samples,1):
            started=time.perf_counter()
            row={'id':index,'file':sample['file'],'image_sha256':sample['sha256'],
                 'reference':{key:sample.get(key) for key in ['label','visible_evidence','reviewer']}}
            try:
                # References, labels, filenames and dataset text are never sent.
                result=await vision.observe([SimpleNamespace(file_path=str(path),photo_type='after')],seed=42)
                row.update(status='ok',result=result)
            except vision.VisionError as error:
                row.update(status='error',error=str(error))
            row['seconds']=round(time.perf_counter()-started,3)
            rows.append(row)
            print(json.dumps({'id':index,'status':row['status'],'seconds':row['seconds']}),flush=True)
            (args.output/'partial-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    finally:
        vision.PROMPT=original_prompt
        stop.set();thread.join(timeout=3)
    report={'version':1,'model':settings.vlm_model,
            'model_sha256':digest(args.model_file),'mmproj_sha256':digest(args.mmproj_file),
            'client_source_sha256':digest(Path(vision.__file__)),
            'prompt_version':prompt_version,'prompt_sha256':fingerprint(prompt),
            'parameters':{'seed':42,'temperature':0.1,'max_tokens':900,'thinking':False,'photos_per_request':1},
            'dataset':{key:manifest.get(key) for key in ['source','license','authors','synthetic','selection']},
            'manifest_sha256':digest(args.manifest),'summary':summary(rows),'results':rows,
            'gpu':{'sample_interval_seconds':0.5,'samples':gpu,
                   'observed_total_max_mib':max(gpu) if gpu else None,
                   'note':'Total GPU use sampled during inference, not a guaranteed peak or model-only allocation'}}
    (args.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (args.output/'review.json').write_text(json.dumps(review_template(report),ensure_ascii=False,indent=2))
    (args.output/'report.html').write_text(render_report(report,args.manifest),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))
    return 1 if report['summary']['errors'] else 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    inference=sub.add_parser('run')
    inference.add_argument('--manifest',type=Path,required=True)
    inference.add_argument('--output',type=Path,required=True,help='New directory, never overwritten')
    inference.add_argument('--url',default='http://127.0.0.1:8081')
    inference.add_argument('--model-file',type=Path,required=True)
    inference.add_argument('--mmproj-file',type=Path,required=True)
    inference.add_argument('--prompt-file',type=Path)
    inference.add_argument('--prompt-version')
    grading=sub.add_parser('review')
    grading.add_argument('results',type=Path)
    grading.add_argument('review',type=Path)
    rendering=sub.add_parser('render')
    rendering.add_argument('results',type=Path)
    rendering.add_argument('manifest',type=Path)
    rendering.add_argument('output',type=Path)
    comparison=sub.add_parser('compare')
    comparison.add_argument('baseline',type=Path)
    comparison.add_argument('candidate',type=Path)
    comparison.add_argument('manifest',type=Path)
    comparison.add_argument('output',type=Path,help='New comparison directory')
    args=parser.parse_args()
    try:
        if args.command=='review':
            print(json.dumps(summarize_review(json.loads(args.results.read_text()),json.loads(args.review.read_text())),ensure_ascii=False,indent=2))
            return 0
        if args.command=='render':
            with args.output.open('x',encoding='utf-8') as output:
                output.write(render_report(json.loads(args.results.read_text()),args.manifest))
            return 0
        if args.command=='compare':
            baseline=json.loads(args.baseline.read_text());candidate=json.loads(args.candidate.read_text())
            compared=compare_reports(baseline,candidate)
            right={row['id']:row for row in candidate['results']}
            combined={**baseline,'prompt_version':baseline['prompt_version']+' vs '+candidate['prompt_version'],
                      'summary':compared,'results':[{**row,'result':{'baseline':row.get('result',row.get('error')),'candidate':right[row['id']].get('result',right[row['id']].get('error'))}} for row in baseline['results']]}
            rendered=render_report(combined,args.manifest)
            args.output.mkdir(parents=True,exist_ok=False)
            (args.output/'comparison.json').write_text(json.dumps(compared,ensure_ascii=False,indent=2))
            (args.output/'comparison.html').write_text(rendered,encoding='utf-8')
            print(json.dumps(compared,ensure_ascii=False,indent=2))
            return 0
        return asyncio.run(run(args))
    except (ValueError,OSError,KeyError) as error:
        parser.error(str(error))


if __name__=='__main__':
    raise SystemExit(main())

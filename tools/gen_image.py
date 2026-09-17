# coding:utf-8
"""
用 Doubao-Seedream 生成图片。

密钥来源（按优先级）：
  1. 环境变量 PARATERA_API_KEY
  2. DSH 的 %APPDATA%\\dsh-desktop\\harness\\.credentials.yaml 里的 refs.PARATERA_API_KEY

为什么直接打 API 而不是走 subagent：subagent 的可用模型是一份「在 Agent 发布时
抓取的」路由策略快照（见 dsh-tool-subagent 的 assertAllowedModelSelection），
中途往 settings.yaml 里加路由不会对已经在跑的会话生效。这个脚本不依赖那条路，
自己带密钥调，什么时候都能用。

用法：
    python tools\\gen_image.py --prompt "..." --out x.png [--size 1024x1024]
    python tools\\gen_image.py --prompt "..." --out x.png --model Doubao-Seedream-4.5
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = os.environ.get('PARATERA_BASE_URL', 'https://llmapi.paratera.com')
DEFAULT_MODEL = 'Doubao-Seedream-4.5'


def api_key():
    k = os.environ.get('PARATERA_API_KEY')
    if k:
        return k.strip()
    p = os.path.join(os.environ.get('APPDATA', ''), 'dsh-desktop',
                     'harness', '.credentials.yaml')
    if os.path.exists(p):
        txt = open(p, encoding='utf-8').read()
        m = re.search(r'PARATERA_API_KEY:\s*([^\s,}]+)', txt)
        if m:
            return m.group(1).strip()
    raise SystemExit('找不到 PARATERA_API_KEY（环境变量和 credentials.yaml 都没有）')


def generate(prompt, out_path, model=DEFAULT_MODEL, size='1024x1024',
             watermark=False, timeout=180):
    body = {
        'model': model,
        'prompt': prompt,
        'size': size,
        'response_format': 'b64_json',
        'watermark': watermark,
    }
    req = urllib.request.Request(
        BASE + '/v1/images/generations',
        data=json.dumps(body).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + api_key(),
                 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:600]
        raise SystemExit('HTTP %s: %s' % (e.code, detail))

    items = payload.get('data') or []
    if not items:
        raise SystemExit('返回里没有图片：%s' % json.dumps(payload)[:600])

    item = items[0]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if item.get('b64_json'):
        raw = base64.b64decode(item['b64_json'])
    elif item.get('url'):
        with urllib.request.urlopen(item['url'], timeout=timeout) as r:
            raw = r.read()
    else:
        raise SystemExit('返回项里既没有 b64_json 也没有 url：%s'
                         % json.dumps(item)[:400])

    # 服务端只会回 JPEG，哪怕你要的是 .png。按实际字节落盘，
    # 需要时再转 —— 否则下游的 PIL / QPixmap 会因为「后缀与内容不符」报错。
    _write_matching(raw, out_path)
    return out_path


def _write_matching(raw, out_path, quality=95):
    """把 raw 按它真实的格式写出去；扩展名对不上就转码。"""
    import io
    from PIL import Image
    fmt = None
    if raw[:3] == b'\xff\xd8\xff':
        fmt = 'JPEG'
    elif raw[:8] == b'\x89PNG\r\n\x1a\n':
        fmt = 'PNG'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        fmt = 'WEBP'

    want = os.path.splitext(out_path)[1].lower().lstrip('.')
    want = {'jpg': 'jpeg'}.get(want, want)
    if fmt is not None and fmt.lower() == want:
        with open(out_path, 'wb') as fh:
            fh.write(raw)
        return fmt

    im = Image.open(io.BytesIO(raw))
    if want == 'png':
        im.convert('RGB' if im.mode not in ('RGBA', 'LA') else 'RGBA').save(
            out_path, 'PNG')
    elif want in ('jpg', 'jpeg'):
        im.convert('RGB').save(out_path, 'JPEG', quality=quality)
    else:
        im.save(out_path)
    return want.upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--model', default=DEFAULT_MODEL)
    ap.add_argument('--size', default='1024x1024')
    ap.add_argument('--watermark', action='store_true')
    a = ap.parse_args()

    p = generate(a.prompt, a.out, a.model, a.size, a.watermark)
    print('wrote %s  %d bytes' % (p, os.path.getsize(p)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
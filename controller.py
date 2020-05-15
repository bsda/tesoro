#!/usr/bin/env python3

import asyncio
from aiohttp import web
from base64 import b64encode
from copy import deepcopy
import json
import jsonpatch
from kapitan.refs.base import RefController, Revealer
import logging

logging.basicConfig(level=logging.INFO)

ROUTES = web.RouteTableDef()
ROUTES_METRICS = web.RouteTableDef()

REF_CONTROLLER = RefController('/tmp', embed_refs=True)
REVEALER = Revealer(REF_CONTROLLER)

@ROUTES_METRICS.get('/metrics')
async def metrics_handler(request):
    return web.Response(text="Metrics go here")

@ROUTES.post('/mutate/{resource}')
async def mutate_resource_handler(request):
    resource = request.match_info.get('resource', None)
    # XXX is this needed at all?
    if resource is None:
        return web.Response(status=500, reason='Resource not set')

    try:
        req_json = await request.json()

        # check for annotation 'kapicorp.com/admiral: kapitan-embed-refs'
        annotated_refs = False
        try:
            annotations = req_json["request"]["object"]["metadata"]["annotations"]
            if annotations["kapicorp.com/admiral"] == "kapitan-embed-refs":
                annotated_refs: True

        # not annotated, default allow
        except KeyError:
            # TODO log success, default allow
            response = make_response([], allow=True, message="")

        req_copy = deepcopy(req_json)

        try:
            reveal_req_func = lambda: kapitan_reveal_json(req_copy)
            req_revealed = await run_blocking(reveal_req_func)
            patch = make_patch(req_json, req_revealed)
            response = make_response(patch, allow=True, message="")

            return web.json_response(response)

        except Exception as e:
            # TODO log exception error
            response = make_response([], allow=False, message="Kapitan Reveal Failed")

            return web.json_response(response)

    except json.decode.JSONDecoderError:
        return web.Response(status=500, reason='Request not JSON')

    return web.Response(status=500, reason='Unknown error')


def make_patch(src_json, dst_json):
    p = jsonpatch.make_patch(src_json, dst_json)
    return p.patch


def make_response(patch, allow=False, message=""):
    patch_json = json.dumps(patch)
    b64_patch = b64encode(patch_json.encode()).decode()
    return {
            "response": {
                "allowed": allow,
                "status": {"message": message},
                "patchType": "JSONPatch",
                "patch": b64_patch
                }
            }


async def run_blocking(func):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func)

def kapitan_reveal_json(json_doc):
    "return revealed object, total revealed tags (TODO)"
    return REVEALER.reveal_obj(json_doc)

async def start_site(app, app_runners, address="localhost", port=8080):
    runner = web.AppRunner(app)
    app_runners.append(runner)
    await runner.setup()
    site = web.TCPSite(runner, address, port)
    await site.start()


if __name__ == '__main__':
    app_runners = []
    app = web.Application()
    app.add_routes(ROUTES)
    app_metrics = web.Application()
    app_metrics.add_routes(ROUTES_METRICS)

    loop = asyncio.get_event_loop()
    loop.create_task(start_site(app, app_runners))
    loop.create_task(start_site(app_metrics, app_runners, port=9095))

    try:
        loop.run_forever()
    except:
        pass
    finally:
        for runner in app_runners:
            loop.run_until_complete(runner.cleanup())

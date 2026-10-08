/* Web Worker que hostea el motor Python (pyodide) FUERA del hilo de UI.
   La página le manda mensajes {id, type, payload} y responde {id, ok, result|error}.
   Así los turnos de los bots corren sin congelar la pantalla. */
/* eslint-disable no-restricted-globals */

const PY_VERSION = "0.26.4";
const PY_BASE = `https://cdn.jsdelivr.net/pyodide/v${PY_VERSION}/full/`;

const BOOTSTRAP = `
import sys, json
sys.path.insert(0, '.')
import interactive
_IG = {'g': None}
def new_game(specs_json, datamap_json, seed, level):
    specs = json.loads(specs_json)
    datamap = json.loads(datamap_json or '{}')
    _IG['g'] = interactive.from_specs(specs, datamap, 0, int(seed), level)
    return json.dumps(_IG['g'].state())
def act(kind, arg_json):
    # si la acción revienta, igual devolvemos el estado ACTUAL (con el error) para
    # que la UI se resincronice en vez de quedar colgada con un estado viejo
    g = _IG['g']; a = json.loads(arg_json or '{}')
    try:
        _act(g, kind, a)
        err = None
    except Exception as e:
        import traceback
        traceback.print_exc()
        err = f"{type(e).__name__}: {e}"
    st = g.state()
    if err:
        st['engine_error'] = err
    return json.dumps(st)
def get_state():
    return json.dumps(_IG['g'].state())
def _act(g, kind, a):
    if kind == 'land': g.play_land(a['i'])
    elif kind == 'cast': g.cast(a.get('i'), a.get('zone', 'hand'), a.get('target_uids'), a.get('mode'))
    elif kind == 'attack': g.attack(a.get('uids', []), a.get('target'), a.get('assign'), a.get('target_pw'))
    elif kind == 'foretell': g.foretell(a.get('i'))
    elif kind == 'activate_gy': g.activate_gy(a.get('i'), a.get('index', 0), a.get('target_uids'))
    elif kind == 'end': g.end_turn()
    elif kind == 'activate': g.activate(a.get('uid'), a.get('index', 0))
    elif kind == 'ability': g.activate_ability(a.get('uid'), a.get('index', 0), a.get('target_uids'))
    elif kind == 'respond': g.respond(a.get('i'), a.get('target_uids'), a.get('mode'))
    elif kind == 'defend': g.resolve_defense(a.get('pairs', []))
    elif kind == 'finish_combat': g.finish_combat()
    elif kind == 'combat_ability': g.activate_in_combat(a.get('uid'), a.get('index', 0), a.get('target_uids'))
    elif kind == 'combat_gy_ability': g.activate_gy_in_combat(a.get('i'), a.get('index', 0), a.get('target_uids'))
    elif kind == 'react': g.react(a.get('action'), a.get('i'), a.get('uid'), a.get('index', 0), a.get('target_uids'))
    elif kind == 'undo': g.undo()
    elif kind == 'choose': g.resolve_choice(a.get('index'))
    elif kind == 'mulligan': g.mulligan()
    elif kind == 'keep': g.keep(a.get('bottom', []))
def export_game():
    return json.dumps(_IG['g'].export())
`;

let py: any = null;
let ready: Promise<any> | null = null;

function post(msg: unknown) { (self as unknown as Worker).postMessage(msg); }

async function ensurePyodide(): Promise<any> {
  if (py) return py;
  if (!ready) {
    ready = (async () => {
      // pyodide.js define loadPyodide en el scope global del worker
      (self as unknown as { importScripts: (u: string) => void }).importScripts(PY_BASE + "pyodide.js");
      const p = await (self as unknown as { loadPyodide: (o: unknown) => Promise<any> })
        .loadPyodide({ indexURL: PY_BASE });
      const res = await fetch("/api/pysrc");
      if (!res.ok) throw new Error(`no se pudo bajar el motor (HTTP ${res.status})`);
      const { modules } = await res.json();
      for (const [name, src] of Object.entries(modules as Record<string, string>)) {
        p.FS.writeFile(name, src as string);
      }
      p.runPython(BOOTSTRAP);
      py = p;
      return p;
    })().catch((err) => {
      ready = null;          // un fallo (red caída) no queda cacheado: se puede reintentar
      throw err;
    });
  }
  return ready;
}

function callPy(fnName: string, args: unknown[]): string {
  const fn = py.globals.get(fnName);
  const raw = fn(...args);
  fn.destroy?.();
  return raw as string;
}

self.onmessage = async (e: MessageEvent) => {
  const { id, type, payload } = e.data || {};
  try {
    if (type === "init") {
      await ensurePyodide();
      post({ id, ok: true, result: null });
    } else if (type === "new_game") {
      await ensurePyodide();
      const raw = callPy("new_game", [payload.specs, payload.datamap, String(payload.seed), payload.level]);
      post({ id, ok: true, result: raw });
    } else if (type === "act") {
      const raw = callPy("act", [payload.kind, payload.arg]);
      post({ id, ok: true, result: raw });
    } else if (type === "state") {
      const raw = callPy("get_state", []);
      post({ id, ok: true, result: raw });
    } else if (type === "export") {
      const raw = callPy("export_game", []);
      post({ id, ok: true, result: raw });
    } else {
      post({ id, ok: false, error: "tipo de mensaje desconocido: " + type });
    }
  } catch (err) {
    post({ id, ok: false, error: err instanceof Error ? err.message : String(err) });
  }
};

from flask import Flask, request, jsonify, render_template, session, Response, stream_with_context
from flask_session import Session
import requests
import json
import uuid
import os
import hashlib
import datetime

app = Flask(__name__)

# ─── SESSION CONFIG ───
# Stockage des sessions dans des fichiers pour survivre aux redémarrages Render
_secret = os.environ.get("SECRET_KEY", "zeno-ia-secret-key-2025-fixed-do-not-change")
app.secret_key = _secret
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=90)
app.config['SESSION_TYPE']              = 'filesystem'
app.config['SESSION_FILE_DIR']          = './flask_sessions'
app.config['SESSION_PERMANENT']         = True
app.config['SESSION_USE_SIGNER']        = True
app.config['SESSION_COOKIE_SECURE']     = bool(os.environ.get("RENDER"))
app.config['SESSION_COOKIE_HTTPONLY']   = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
app.config['SESSION_COOKIE_NAME']       = 'zeno_session'
app.config['SESSION_COOKIE_DOMAIN']     = None

# Créer le dossier de sessions si nécessaire
os.makedirs('./flask_sessions', exist_ok=True)
Session(app)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-8b-8192"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

DB_FILE     = "conversations.json"
USERS_FILE  = "users.json"
TOKENS_FILE = "tokens.json"

VIP_EMAIL = "arturo14mix@gmail.com"

ZENO_SYSTEM = """Tu es Zeno, une IA de nouvelle génération créée pour être l'assistant le plus intelligent, utile et agréable possible.

TES CAPACITÉS :
- Tu es une experte absolue en programmation : Python, JavaScript, TypeScript, HTML/CSS, React, Vue, Node.js, Flask, Django, SQL, MongoDB, Git, Docker, algorithmes, design patterns. Tu écris du code propre, optimisé, commenté.
- Tu analyses, débogues et optimises du code existant.
- Tu maîtrises les mathématiques, les sciences, la philosophie, l'histoire et la culture générale.
- Tu peux rédiger et améliorer tout type de texte.
- Si quelqu'un te demande de générer une image dans le chat texte, dis-lui d'utiliser le bouton + en bas à gauche.
- Quand tu montres du code, tu utilises TOUJOURS des blocs ``` avec le langage.

TON STYLE :
- Directe, intelligente, tu vas droit au but.
- Tu réponds TOUJOURS en français sauf si on te parle dans une autre langue.
- Tu es confiante et chaleureuse.
- En mode RAPIDE : max 3-4 phrases ou un bloc de code concis.
- En mode EQUILIBRE : réponse complète et claire.
- En mode APPROFONDI : analyse exhaustive, exemples multiples.

MODE VOCAL :
- Réponds naturellement en 2-3 phrases courtes max. Pas de markdown, pas de listes.

RÈGLES :
- Tu es Zeno de Zeno IA. Tu ne mentionnes jamais Llama, Meta, Groq ou Ollama."""

# ─── DATA HELPERS ───
def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(d):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(u, f, indent=2, ensure_ascii=False)

def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tokens(t):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=2, ensure_ascii=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_plan(email):
    if email.lower() == VIP_EMAIL.lower():
        return "expert"
    users = load_users()
    return users.get(email.lower(), {}).get("plan", "free")

def make_remember_token(email):
    token  = str(uuid.uuid4()) + str(uuid.uuid4())
    tokens = load_tokens()
    now    = datetime.datetime.now().timestamp()
    tokens = {k: v for k, v in tokens.items() if v.get("expires", 0) > now}
    tokens[token] = {
        "email":   email,
        "expires": (datetime.datetime.now() + datetime.timedelta(days=90)).timestamp()
    }
    save_tokens(tokens)
    return token

def verify_remember_token(token):
    if not token:
        return None
    tokens = load_tokens()
    entry  = tokens.get(token)
    if not entry:
        return None
    if entry.get("expires", 0) < datetime.datetime.now().timestamp():
        del tokens[token]
        save_tokens(tokens)
        return None
    return entry.get("email")

# ─── AI ───
WEB_SEARCH_KEYWORDS = [
    "actualité", "actualités", "news", "aujourd'hui", "cette semaine", "ce mois",
    "en ce moment", "dernière", "dernier", "récent", "récente", "nouveauté",
    "vient de", "annoncé", "2024", "2025", "maintenant", "live", "direct",
    "météo", "cours", "bourse", "prix", "résultat", "score", "classement",
    "élection", "guerre", "conflit", "événement", "sortie", "lancement"
]

def needs_web_search(message):
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in WEB_SEARCH_KEYWORDS)

def do_web_search(query):
    try:
        url  = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "ZenoIA/1.0"})
        data = resp.json()
        results = []
        if data.get("AbstractText"):
            results.append(f"Résumé: {data['AbstractText']}")
        for topic in data.get("RelatedTopics", [])[:4]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"])
        if results:
            return "Résultats pour '" + query + "':\n" + "\n".join(results)
        return f"Aucun résultat pour '{query}'."
    except Exception as e:
        return f"Recherche impossible: {str(e)}"

def call_ai(messages, mode="balanced"):
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)
    last_user  = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

    if GROQ_API_KEY:
        try:
            # Inject web search results directly into system prompt if needed
            msgs_to_send = list(messages)
            if needs_web_search(last_user):
                search_results = do_web_search(last_user)
                if msgs_to_send and msgs_to_send[0]["role"] == "system":
                    msgs_to_send[0] = dict(msgs_to_send[0])
                    msgs_to_send[0]["content"] += f"\n\nRésultats de recherche web actuels:\n{search_results}"

            payload = {
                "model": GROQ_MODEL, "messages": msgs_to_send,
                "max_tokens": max_tokens, "temperature": 0.7, "top_p": 0.9,
            }

            resp = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json=payload, timeout=55)
            resp.raise_for_status()
            data   = resp.json()
            if "choices" not in data or not data["choices"]:
                return "Je n'ai pas pu générer de réponse. Réessaie."
            choice = data["choices"][0]
            msg    = choice.get("message", {})

            if choice.get("finish_reason") == "tool_calls" and msg.get("tool_calls"):
                tool_call      = msg["tool_calls"][0]
                query          = json.loads(tool_call["function"]["arguments"]).get("query", last_user)
                search_results = do_web_search(query)
                # Rebuild messages with search results injected into system prompt
                # instead of tool_calls format to avoid Groq 400 errors
                messages2 = list(messages)
                messages2[0]["content"] += f"\n\nRésultats de recherche web:\n{search_results}"
                resp2 = requests.post(GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": GROQ_MODEL, "messages": messages2, "max_tokens": max_tokens, "temperature": 0.7},
                    timeout=55)
                resp2.raise_for_status()
                data2 = resp2.json()
                if "choices" in data2 and data2["choices"]:
                    return data2["choices"][0]["message"]["content"].strip()
                return "Je n'ai pas pu obtenir de réponse."

            content = msg.get("content", "")
            return content.strip() if content else "Je n'ai pas pu générer de réponse."

        except requests.exceptions.Timeout:
            return "La réponse a pris trop de temps. Réessaie avec le mode Rapide."
        except Exception as e:
            return f"Erreur: {str(e)}"
    else:
        prompt_text = ""
        for m in messages:
            if m["role"] == "system":      prompt_text += m["content"] + "\n\n"
            elif m["role"] == "user":      prompt_text += f"Utilisateur: {m['content']}\n"
            elif m["role"] == "assistant": prompt_text += f"Zeno: {m['content']}\n"
        prompt_text += "Zeno:"
        try:
            resp = requests.post(OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt_text, "stream": False,
                      "options": {"temperature": 0.7, "num_predict": max_tokens}},
                timeout=120)
            return resp.json().get("response", "").strip()
        except Exception as e:
            return f"Erreur Ollama: {str(e)}"

def generate_title(user_message, assistant_reply):
    prompt = (
        "Génère un titre de 3 mots maximum (pas de ponctuation, pas de guillemets) "
        f"pour cette conversation.\nQuestion: {user_message[:100]}\nTitre:"
    )
    try:
        if GROQ_API_KEY:
            resp = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 12, "temperature": 0.3, "stop": ["\n", ".", "!", "?"]},
                timeout=8)
            if resp.status_code == 200:
                data  = resp.json()
                if "choices" in data and data["choices"]:
                    title = data["choices"][0]["message"]["content"].strip()
                    title = title.replace('"','').replace("'",'').replace('\n',' ')
                    title = ' '.join(title.split()[:4])
                    if title and len(title) > 2:
                        return title
    except:
        pass
    words = user_message.strip().split()
    return ' '.join(words[:4]) if words else "Conversation"

data = load_data()

# ─── PAGES ───
@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/app")
def app_page():
    return render_template("index.html")

# ─── AUTH ───
@app.route("/register", methods=["POST"])
def register():
    body   = request.json or {}
    email  = (body.get("email") or "").strip().lower()
    pw     = body.get("password", "")
    prenom = body.get("prenom", "").strip()
    if not email or not pw:
        return jsonify({"ok": False, "error": "Email et mot de passe requis."})
    users = load_users()
    if email in users:
        return jsonify({"ok": False, "error": "Un compte existe déjà avec cet email."})
    users[email] = {"email": email, "prenom": prenom, "pw": hash_pw(pw), "plan": "free"}
    save_users(users)
    session.permanent = True
    session["email"]  = email
    session["prenom"] = prenom
    session["plan"]   = get_plan(email)
    token = make_remember_token(email)
    resp  = jsonify({"ok": True, "plan": session["plan"]})
    resp.set_cookie("zeno_remember", token, max_age=90*24*3600,
                    httponly=True, secure=bool(os.environ.get("RENDER")), samesite="Lax")
    return resp

@app.route("/login", methods=["POST"])
def login():
    body        = request.json or {}
    email       = (body.get("email") or "").strip().lower()
    pw          = body.get("password", "")
    remember_me = body.get("remember_me", True)
    if not email or not pw:
        return jsonify({"ok": False, "error": "Email et mot de passe requis."})
    if email == VIP_EMAIL.lower():
        session.permanent = True
        session["email"]  = email
        session["prenom"] = "Arturo"
        session["plan"]   = "expert"
        token = make_remember_token(email)
        resp  = jsonify({"ok": True, "plan": "expert"})
        resp.set_cookie("zeno_remember", token, max_age=90*24*3600,
                        httponly=True, secure=bool(os.environ.get("RENDER")), samesite="Lax")
        return resp
    users = load_users()
    user  = users.get(email)
    if not user or user.get("pw") != hash_pw(pw):
        return jsonify({"ok": False, "error": "Email ou mot de passe incorrect."})
    session.permanent = True
    session["email"]  = email
    session["prenom"] = user.get("prenom", "")
    session["plan"]   = get_plan(email)
    resp = jsonify({"ok": True, "plan": session["plan"]})
    if remember_me:
        token = make_remember_token(email)
        resp.set_cookie("zeno_remember", token, max_age=90*24*3600,
                        httponly=True, secure=bool(os.environ.get("RENDER")), samesite="Lax")
    return resp

@app.route("/logout", methods=["POST"])
def logout():
    token = request.cookies.get("zeno_remember")
    if token:
        tokens = load_tokens()
        tokens.pop(token, None)
        save_tokens(tokens)
    session.clear()
    resp = jsonify({"ok": True})
    resp.delete_cookie("zeno_remember")
    return resp

@app.route("/me")
def me():
    # 1. Session Flask active
    if "email" in session:
        return jsonify({"ok": True, "email": session["email"],
                        "prenom": session.get("prenom",""), "plan": session.get("plan","free")})
    # 2. Cookie remember_me
    token = request.cookies.get("zeno_remember")
    email = verify_remember_token(token)
    if email:
        plan   = get_plan(email)
        users  = load_users()
        user   = users.get(email, {})
        prenom = "Arturo" if email == VIP_EMAIL.lower() else user.get("prenom", "")
        session.permanent = True
        session["email"]  = email
        session["prenom"] = prenom
        session["plan"]   = plan
        return jsonify({"ok": True, "email": email, "prenom": prenom, "plan": plan})
    return jsonify({"ok": False})

# ─── CONVERSATIONS ───
@app.route("/conversations")
def conversations():
    return jsonify({"conversations": [
        {"id": cid, "title": data[cid]["title"], "date": data[cid].get("date", "")}
        for cid in data
    ]})

@app.route("/conversation/<cid>")
def get_conv(cid):
    return jsonify(data.get(cid, {"messages": []}))

@app.route("/new", methods=["POST"])
def new_conv():
    cid = str(uuid.uuid4())[:8]
    data[cid] = {"title": "Nouvelle conversation", "messages": [], "date": datetime.datetime.now().isoformat()}
    save_data(data)
    return jsonify({"id": cid})

def stream_groq(messages, mode="balanced"):
    """Stream depuis Groq token par token."""
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "messages": messages, "max_tokens": max_tokens,
              "temperature": 0.7, "stream": True},
        stream=True, timeout=60
    )
    full_reply = ""
    for line in resp.iter_lines():
        if line:
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "): line_str = line_str[6:]
            if line_str == "[DONE]":
                yield full_reply, True
                return
            try:
                chunk = json.loads(line_str)
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    full_reply += token
                    yield token, False
            except: continue
    yield full_reply, True

def stream_ollama(messages, mode="balanced"):
    """Stream depuis Ollama token par token."""
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)
    prompt_text = ""
    for m in messages:
        if m["role"] == "system":      prompt_text += m["content"] + "\n\n"
        elif m["role"] == "user":      prompt_text += f"Utilisateur: {m['content']}\n"
        elif m["role"] == "assistant": prompt_text += f"Zeno: {m['content']}\n"
    prompt_text += "Zeno:"
    resp = requests.post(OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt_text, "stream": True,
              "options": {"temperature": 0.7, "num_predict": max_tokens}},
        stream=True, timeout=120)
    full_reply = ""
    for line in resp.iter_lines():
        if line:
            try:
                chunk = json.loads(line.decode("utf-8"))
                token = chunk.get("response", "")
                if token:
                    full_reply += token
                    yield token, False
                if chunk.get("done"):
                    yield full_reply, True
                    return
            except: continue
    yield full_reply, True

@app.route("/chat/<cid>", methods=["POST"])
def chat(cid):
    message  = request.json.get("message", "")
    mode     = request.json.get("mode", "balanced")
    is_voice = request.json.get("voice", False)

    if cid not in data:
        data[cid] = {"title": "Nouvelle conversation", "messages": [], "date": datetime.datetime.now().isoformat()}

    conv = data[cid]
    conv["messages"].append({"role": "user", "text": message})

    if is_voice:
        mode_instr = "MODE VOCAL : Réponds en 2-3 phrases max, naturellement. Pas de markdown."
    elif mode == "fast":
        mode_instr = "Réponds de façon COURTE et DIRECTE. Maximum 3-4 phrases ou un bloc de code concis."
    elif mode == "deep":
        mode_instr = "Réponse TRÈS DÉTAILLÉE avec exemples multiples et explications étape par étape."
    else:
        mode_instr = "Réponse complète et claire, sans longueur inutile."

    # Inject web search if needed
    msgs_to_send = list(messages if False else [])
    base_messages = [{"role": "system", "content": ZENO_SYSTEM + f"\n\n{mode_instr}"}]
    for m in conv["messages"][:-1]:
        base_messages.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]})
    base_messages.append({"role": "user", "content": message})

    if needs_web_search(message):
        search_results = do_web_search(message)
        base_messages[0] = dict(base_messages[0])
        base_messages[0]["content"] += f"\n\nRésultats de recherche web actuels:\n{search_results}"

    # Voice: non-streaming
    if is_voice:
        reply = call_ai(base_messages, mode)
        conv["messages"].append({"role": "assistant", "text": reply})
        if len(conv["messages"]) == 2:
            conv["title"] = generate_title(message, reply)
        save_data(data)
        return jsonify({"response": reply, "title": conv["title"]})

    # Text: streaming SSE
    def generate():
        full_reply = ""
        try:
            streamer = stream_groq(base_messages, mode) if GROQ_API_KEY else stream_ollama(base_messages, mode)
            for token, is_done in streamer:
                if not is_done:
                    yield f"data: {json.dumps({'token': token})}\n\n"
                else:
                    full_reply = token
            conv["messages"].append({"role": "assistant", "text": full_reply})
            if len(conv["messages"]) == 2:
                conv["title"] = generate_title(message, full_reply)
            save_data(data)
            yield f"data: {json.dumps({'done': True, 'title': conv['title']})}\n\n"
        except Exception as e:
            error_msg = f"Erreur: {str(e)}"
            yield f"data: {json.dumps({'token': error_msg})}\n\n"
            yield f"data: {json.dumps({'done': True, 'title': conv.get('title', 'Conversation')})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.route("/delete/<cid>", methods=["POST"])
def delete(cid):
    if cid in data:
        del data[cid]
        save_data(data)
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
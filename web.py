from flask import Flask, request, jsonify, render_template, session, Response, stream_with_context
import requests
import json
import uuid
import os
import hashlib
import datetime

app = Flask(__name__)

# SECRET_KEY fixe et stable - ne pas changer sinon sessions perdues
_secret = os.environ.get("SECRET_KEY", "zeno-ia-secret-key-2025-fixed-do-not-change")
app.secret_key = _secret
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=90)
app.config['SESSION_COOKIE_SECURE']   = os.environ.get("RENDER", False) and True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME']     = 'zeno_session'

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-70b-8192"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

DB_FILE      = "conversations.json"
USERS_FILE   = "users.json"
TOKENS_FILE  = "tokens.json"   # Pour les "rester connecté" persistants

VIP_EMAIL = "arturo14mix@gmail.com"

ZENO_SYSTEM = """Tu es Zeno, une IA de nouvelle génération créée pour être l'assistant le plus intelligent, utile et agréable possible.

TES CAPACITÉS :
- Tu es une experte absolue en programmation : Python, JavaScript, TypeScript, HTML/CSS, React, Vue, Node.js, Flask, Django, SQL, MongoDB, Git, Docker, algorithmes, design patterns, architecture logicielle. Tu écris du code propre, optimisé, commenté, avec des exemples concrets et complets.
- Tu analyses, débogues et optimises du code existant. Tu détectes les bugs et proposes des solutions précises.
- Tu maîtrises les mathématiques, les sciences, la philosophie, l'histoire, la géographie et la culture générale.
- Tu peux rédiger et améliorer tout type de texte : emails, articles, essais, histoires, CV, lettres de motivation.
- Si quelqu'un te demande de générer une image dans le chat texte, dis-lui d'utiliser le bouton + en bas à gauche, puis "Générer une image".
- Quand tu montres du code, tu utilises TOUJOURS des blocs ``` avec le langage (ex: ```python).

TON STYLE :
- Directe, intelligente, tu vas droit au but. Pas de remplissage.
- Tu réponds TOUJOURS en français sauf si on te parle dans une autre langue.
- Tu es confiante et chaleureuse, sans être servile.
- En mode RAPIDE : réponse courte et précise, max 3-4 phrases ou un bloc de code concis.
- En mode EQUILIBRE : réponse complète avec explications claires.
- En mode APPROFONDI : analyse exhaustive, exemples multiples, étape par étape, bonnes pratiques, pièges.

MODE VOCAL :
- Quand tu réponds à un message vocal, sois naturelle et conversationnelle. Pas de listes, pas de markdown. Parle comme dans une vraie conversation. Maximum 3 phrases courtes.

RÈGLES :
- Ne dis jamais que tu es incapable sans avoir essayé.
- Pour le code, toujours un exemple complet et fonctionnel.
- Formate : **gras** pour points importants, `code` pour termes techniques.
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
    """Génère un token unique pour rester connecté."""
    token = str(uuid.uuid4()) + str(uuid.uuid4())
    tokens = load_tokens()
    # Nettoyage des tokens expirés
    now = datetime.datetime.now().timestamp()
    tokens = {k: v for k, v in tokens.items() if v.get("expires", 0) > now}
    tokens[token] = {
        "email": email,
        "expires": (datetime.datetime.now() + datetime.timedelta(days=90)).timestamp()
    }
    save_tokens(tokens)
    return token

def verify_remember_token(token):
    """Vérifie un token et retourne l'email si valide."""
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

data = load_data()

# ─── AI HELPERS ───
def generate_title(user_message, assistant_reply):
    prompt = f"""Génère un titre TRÈS COURT (3 à 5 mots maximum, sans ponctuation, sans guillemets, sans emoji) qui résume cette conversation.
Message utilisateur : {user_message[:200]}
Réponse IA : {assistant_reply[:200]}
Titre (3-5 mots seulement) :"""
    try:
        if GROQ_API_KEY:
            resp = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 20, "temperature": 0.5}, timeout=15)
            title = resp.json()["choices"][0]["message"]["content"].strip()
        else:
            resp = requests.post(OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": 20, "temperature": 0.5}}, timeout=30)
            title = resp.json().get("response", "").strip()
        title = title.replace('"','').replace("'",'').replace('\n',' ').strip()
        return ' '.join(title.split()[:6]) or user_message[:40]
    except:
        return user_message[:40]

def stream_ollama(messages, mode="balanced"):
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)
    prompt_text = ""
    for m in messages:
        if m["role"] == "system":      prompt_text += m["content"] + "\n\n"
        elif m["role"] == "user":      prompt_text += f"Utilisateur: {m['content']}\n"
        elif m["role"] == "assistant": prompt_text += f"Zeno: {m['content']}\n"
    prompt_text += "Zeno:"
    resp = requests.post(OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt_text, "stream": True,
              "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": max_tokens}},
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

def stream_groq(messages, mode="balanced"):
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)
    resp = requests.post(GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "messages": messages, "max_tokens": max_tokens,
              "temperature": 0.7, "stream": True},
        stream=True, timeout=60)
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

def call_ai_simple(messages, mode="balanced"):
    max_tokens = 512 if mode == "fast" else 1024
    if GROQ_API_KEY:
        try:
            resp = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7},
                timeout=60)
            return resp.json()["choices"][0]["message"]["content"].strip()
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
                      "options": {"temperature": 0.7, "num_predict": max_tokens}}, timeout=120)
            return resp.json().get("response", "").strip()
        except Exception as e:
            return f"Erreur: {str(e)}"

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
    # Token "rester connecté" automatique à l'inscription
    token = make_remember_token(email)
    resp  = jsonify({"ok": True, "plan": session["plan"], "remember_token": token})
    resp.set_cookie("zeno_remember", token, max_age=90*24*3600, httponly=True,
                    secure=bool(os.environ.get("RENDER")), samesite="Lax")
    return resp

@app.route("/login", methods=["POST"])
def login():
    body        = request.json or {}
    email       = (body.get("email") or "").strip().lower()
    pw          = body.get("password", "")
    remember_me = body.get("remember_me", True)
    if not email or not pw:
        return jsonify({"ok": False, "error": "Email et mot de passe requis."})
    # VIP
    if email == VIP_EMAIL.lower():
        session.permanent = True
        session["email"]  = email
        session["prenom"] = "Arturo"
        session["plan"]   = "expert"
        token = make_remember_token(email)
        resp  = jsonify({"ok": True, "plan": "expert"})
        resp.set_cookie("zeno_remember", token, max_age=90*24*3600, httponly=True,
                        secure=bool(os.environ.get("RENDER")), samesite="Lax")
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
        resp.set_cookie("zeno_remember", token, max_age=90*24*3600, httponly=True,
                        secure=bool(os.environ.get("RENDER")), samesite="Lax")
    return resp

@app.route("/logout", methods=["POST"])
def logout():
    # Invalide le token remember
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
    # 1. Vérifie la session Flask
    if "email" in session:
        return jsonify({"ok": True, "email": session["email"],
                        "prenom": session.get("prenom",""), "plan": session.get("plan","free")})
    # 2. Vérifie le cookie "rester connecté"
    token = request.cookies.get("zeno_remember")
    email = verify_remember_token(token)
    if email:
        # Recrée la session
        plan   = get_plan(email)
        prenom = "Arturo" if email == VIP_EMAIL.lower() else ""
        users  = load_users()
        user   = users.get(email, {})
        prenom = user.get("prenom", prenom)
        session.permanent = True
        session["email"]  = email
        session["prenom"] = prenom
        session["plan"]   = plan
        return jsonify({"ok": True, "email": email, "prenom": prenom, "plan": plan})
    return jsonify({"ok": False})

# ─── CONVERSATIONS ───
@app.route("/conversations")
def conversations():
    return jsonify({"conversations": [{"id": cid, "title": data[cid]["title"]} for cid in data]})

@app.route("/conversation/<cid>")
def get_conv(cid):
    return jsonify(data.get(cid, {"messages": []}))

@app.route("/new", methods=["POST"])
def new_conv():
    cid = str(uuid.uuid4())[:8]
    data[cid] = {"title": "Nouvelle conversation", "messages": []}
    save_data(data)
    return jsonify({"id": cid})

@app.route("/chat/<cid>", methods=["POST"])
def chat(cid):
    message  = request.json.get("message", "")
    mode     = request.json.get("mode", "balanced")
    is_voice = request.json.get("voice", False)
    if cid not in data:
        data[cid] = {"title": "Nouvelle conversation", "messages": []}
    conv = data[cid]
    conv["messages"].append({"role": "user", "text": message})
    if is_voice:
        mode_instr = "MODE VOCAL : Réponds naturellement et brièvement en 2-3 phrases max. Pas de markdown, pas de listes, juste une vraie conversation."
    elif mode == "fast":
        mode_instr = "IMPORTANT : Réponds de façon COURTE et DIRECTE. Maximum 3-4 phrases ou un bloc de code concis."
    elif mode == "deep":
        mode_instr = "IMPORTANT : Réponse TRÈS DÉTAILLÉE. Analyse en profondeur, exemples multiples, étape par étape."
    else:
        mode_instr = "Réponse complète et claire, sans longueur inutile."
    messages = [{"role": "system", "content": ZENO_SYSTEM + f"\n\n{mode_instr}"}]
    for m in conv["messages"][:-1]:
        messages.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]})
    messages.append({"role": "user", "content": message})
    # Voice: non-streaming
    if is_voice:
        reply = call_ai_simple(messages, mode)
        conv["messages"].append({"role": "assistant", "text": reply})
        if len(conv["messages"]) == 2:
            conv["title"] = generate_title(message, reply)
        save_data(data)
        return jsonify({"response": reply, "title": conv["title"]})
    # Text: streaming
    def generate():
        full_reply = ""
        try:
            streamer = stream_groq(messages, mode) if GROQ_API_KEY else stream_ollama(messages, mode)
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
            yield f"data: {json.dumps({'token': f'Erreur: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'title': conv['title']})}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/delete/<cid>", methods=["POST"])
def delete(cid):
    if cid in data:
        del data[cid]
        save_data(data)
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
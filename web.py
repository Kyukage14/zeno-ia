from flask import Flask, request, jsonify, render_template, session, Response, stream_with_context
import requests
import json
import uuid
import os
import hashlib
import datetime

app = Flask(__name__)

_secret = os.environ.get("SECRET_KEY", "zeno-ia-secret-key-2025-fixed-do-not-change")
app.secret_key = _secret
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=90)
app.config['SESSION_COOKIE_SECURE']   = bool(os.environ.get("RENDER"))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_NAME']     = 'zeno_session'

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL   = "llama3-8b-8192"   # modele plus stable et rapide

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
- Réponds naturellement en 2-3 phrases courtes max. Pas de markdown, pas de listes. Parle comme dans une vraie conversation.

RÈGLES :
- Tu es Zeno de Zeno IA. Tu ne mentionnes jamais Llama, Meta, Groq ou Ollama."""

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

def call_ai(messages, mode="balanced"):
    """Appel IA robuste avec fallback et gestion d'erreurs complète."""
    max_tokens = 4096 if mode == "deep" else (512 if mode == "fast" else 2048)

    if GROQ_API_KEY:
        try:
            resp = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type":  "application/json"
                },
                json={
                    "model":       GROQ_MODEL,
                    "messages":    messages,
                    "max_tokens":  max_tokens,
                    "temperature": 0.7,
                    "top_p":       0.9,
                },
                timeout=55
            )
            resp.raise_for_status()
            data = resp.json()
            # Vérification robuste de la réponse
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"].strip()
            elif "error" in data:
                return f"Erreur Groq: {data['error'].get('message', 'inconnue')}"
            else:
                return "Je n'ai pas pu générer de réponse. Réessaie."
        except requests.exceptions.Timeout:
            return "La réponse a pris trop de temps. Réessaie avec le mode Rapide."
        except requests.exceptions.HTTPError as e:
            return f"Erreur de connexion à l'IA ({e.response.status_code}). Réessaie."
        except Exception as e:
            return f"Erreur inattendue: {str(e)}"
    else:
        # Fallback Ollama local
        prompt_text = ""
        for m in messages:
            if m["role"] == "system":      prompt_text += m["content"] + "\n\n"
            elif m["role"] == "user":      prompt_text += f"Utilisateur: {m['content']}\n"
            elif m["role"] == "assistant": prompt_text += f"Zeno: {m['content']}\n"
        prompt_text += "Zeno:"
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":   OLLAMA_MODEL,
                    "prompt":  prompt_text,
                    "stream":  False,
                    "options": {"temperature": 0.7, "num_predict": max_tokens}
                },
                timeout=120
            )
            return resp.json().get("response", "").strip()
        except Exception as e:
            return f"Erreur Ollama: {str(e)}"

def generate_title(user_message, assistant_reply):
    prompt = f"""Génère un titre TRÈS COURT de 3 à 4 mots maximum (sans ponctuation, sans guillemets, sans emoji) qui résume cette conversation.
Message: {user_message[:150]}
Réponse: {assistant_reply[:150]}
Titre:"""
    try:
        if GROQ_API_KEY:
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 15, "temperature": 0.3},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if "choices" in data:
                title = data["choices"][0]["message"]["content"].strip()
                title = title.replace('"','').replace("'",'').replace('\n',' ').strip()
                return ' '.join(title.split()[:5]) or user_message[:35]
        return user_message[:35]
    except:
        return user_message[:35]

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
    if "email" in session:
        return jsonify({"ok": True, "email": session["email"],
                        "prenom": session.get("prenom",""), "plan": session.get("plan","free")})
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
        mode_instr = "MODE VOCAL : Réponds en 2-3 phrases max, naturellement. Pas de markdown, pas de listes."
    elif mode == "fast":
        mode_instr = "Réponds de façon COURTE et DIRECTE. Maximum 3-4 phrases ou un bloc de code concis."
    elif mode == "deep":
        mode_instr = "Réponse TRÈS DÉTAILLÉE avec exemples multiples et explications étape par étape."
    else:
        mode_instr = "Réponse complète et claire, sans longueur inutile."

    messages = [{"role": "system", "content": ZENO_SYSTEM + f"\n\n{mode_instr}"}]
    for m in conv["messages"][:-1]:
        messages.append({
            "role":    "user" if m["role"] == "user" else "assistant",
            "content": m["text"]
        })
    messages.append({"role": "user", "content": message})

    reply = call_ai(messages, mode)

    conv["messages"].append({"role": "assistant", "text": reply})
    if len(conv["messages"]) == 2:
        conv["title"] = generate_title(message, reply)
    save_data(data)

    return jsonify({"response": reply, "title": conv["title"]})

@app.route("/delete/<cid>", methods=["POST"])
def delete(cid):
    if cid in data:
        del data[cid]
        save_data(data)
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
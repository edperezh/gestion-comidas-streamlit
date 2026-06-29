# Gestión de Comidas - Streamlit

App para controlar una tiquetera mensual de comidas por usuario.

## Características

- Valor mensual: $480.000 COP.
- 30 desayunos de $7.000.
- 30 almuerzos de $9.000.
- Perfiles por correo.
- PIN opcional por perfil.
- Botón **Guardar perfil**.
- Modo oscuro por defecto.
- Registro diario de desayuno y almuerzo.
- Resumen mensual, calendario y exportación CSV.
- Lista para subir a un repositorio privado de GitHub y publicar en Streamlit Community Cloud.

## 1. Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Si no configuras Supabase, la app usará SQLite local (`comidas.db`). Ese modo sirve para probar en tu computador, pero no es recomendable para varios usuarios usando un link público.

## 2. Base de datos para producción: Supabase

GitHub guarda el código, pero no debe usarse como base de datos. Para que varios usuarios puedan registrar comidas desde el link sin perder información, usa Supabase.

Crea un proyecto en Supabase y ejecuta este SQL en el editor SQL:

```sql
create table if not exists users_meals (
  email text primary key,
  name text,
  pin_hash text,
  created_at timestamp default now()
);

create table if not exists meal_logs (
  id uuid primary key default gen_random_uuid(),
  email text not null references users_meals(email) on delete cascade,
  meal_date date not null,
  meal_type text not null check (meal_type in ('desayuno', 'almuerzo')),
  created_at timestamp default now(),
  unique(email, meal_date, meal_type)
);
```

En Streamlit Community Cloud agrega estos secrets:

```toml
SUPABASE_URL = "https://TU-PROYECTO.supabase.co"
SUPABASE_KEY = "TU-ANON-KEY"
```

No subas `secrets.toml` a GitHub. El archivo `.gitignore` ya lo excluye.

## 3. Subir a GitHub privado

1. Entra a GitHub.
2. Crea un repositorio nuevo.
3. Marca la opción **Private**.
4. Sube estos archivos y carpetas:

```text
streamlit_app.py
requirements.txt
README.md
.gitignore
.streamlit/config.toml
.streamlit/secrets.example.toml
```

No subas:

```text
.streamlit/secrets.toml
comidas.db
```

## 4. Publicar con link en Streamlit Community Cloud

1. Entra a Streamlit Community Cloud.
2. Conecta tu cuenta de GitHub.
3. Crea una app nueva.
4. Selecciona el repositorio privado.
5. Archivo principal: `streamlit_app.py`.
6. En **Secrets**, pega las credenciales de Supabase.
7. Dale **Deploy**.
8. Comparte el link de Streamlit con los usuarios.

Importante: esto no se publica con GitHub Pages. GitHub Pages sirve para páginas estáticas; Streamlit necesita ejecutar Python, por eso se publica en Streamlit Community Cloud.

## 5. Flujo de uso

1. El usuario escribe su correo.
2. Escribe su nombre opcional.
3. Escribe un PIN opcional.
4. Presiona **Guardar perfil**.
5. Luego entra con correo y PIN.
6. Registra desayuno o almuerzo cada día.
7. Consulta el resumen mensual.

## 6. Mejoras futuras

- Login real con Google.
- Panel administrador.
- Recordatorio automático cuando falten comidas por consumir.
- Reporte PDF mensual.
- Control de varias tiqueteras o diferentes planes.

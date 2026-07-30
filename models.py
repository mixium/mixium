from decimal import Decimal, InvalidOperation

from sqlalchemy import text
from models import *
from db_connect import (
    execute_select_query,
    execute_modify_query,
    execute_insert_returning_id,
    get_db,
)


def _none_if_blank(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _to_decimal(value):
    value = _none_if_blank(value)
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


# ==========================================================
# Materials
# ==========================================================

def list_materials(search=None, material_type=None):
    query = """
        SELECT
            m."id_MaterialEspecie"       AS id,
            m."NomeComercial"            AS commercial_name,
            m."MarcaComercial"           AS brand,
            m."MassaEspecifica_g_cm3"    AS specific_mass,
            m.tipo_material              AS material_type
        FROM "MaterialEspecie" AS m
        WHERE (:search IS NULL OR m."NomeComercial" ILIKE :search OR m."MarcaComercial" ILIKE :search)
          AND (:material_type IS NULL OR m.tipo_material::text = :material_type)
        ORDER BY m."NomeComercial";
    """

    params = {
        "search": f"%{search}%" if _none_if_blank(search) else None,
        "material_type": _none_if_blank(material_type),
    }

    return execute_select_query(query, params) or []


def create_material(data):
    query = """
        INSERT INTO "MaterialEspecie"
            ("NomeComercial", "MarcaComercial", "MassaEspecifica_g_cm3", tipo_material)
        VALUES
            (:commercial_name, :brand, :specific_mass, :material_type)
        RETURNING "id_MaterialEspecie";
    """

    params = {
        "commercial_name": _none_if_blank(data.get("commercial_name")),
        "brand": _none_if_blank(data.get("brand")),
        "specific_mass": _to_decimal(data.get("specific_mass")),
        "material_type": _none_if_blank(data.get("material_type")),
    }

    return execute_insert_returning_id(query, params)


def get_material_types():
    query = """
        SELECT unnest(enum_range(NULL::"enum_tipos_materialespecie")) AS value;
    """
    rows = execute_select_query(query)
    return [row["value"] for row in rows] if rows else []


# ==========================================================
# Mixes
# ==========================================================

def list_mixes():
    query = """
        SELECT
            "id_Traco"          AS id,
            "Nome"              AS name,
            "TipoConcreto"      AS concrete_type,
            "Cor"               AS color,
            "fck28_MPa"             AS fck28,
            "SlumpAlvo_cm"         AS target_slump,
            "ConsumoCimento_kg_m3"    AS cement_consumption,
            "massaespecifica_real_kg_m3"   AS specific_mass
        FROM "Traco"
        ORDER BY "Nome";
    """
    return execute_select_query(query)


def create_mix(data):
    engine = get_db()

    mix_query = text("""
        INSERT INTO "Traco"
            ("Nome", "TipoConcreto", "Cor", "fck28_MPa", "SlumpAlvo_cm", "ConsumoCimento_kg_m3", "massaespecifica_real_kg_m3")
        VALUES
            (:mix_name, :concrete_type, :color, :fck28, :target_slump, :cement_consumption, :specific_mass)
        RETURNING "id_Traco";
    """)

    mix_params = {
        "mix_name": _none_if_blank(data.get("mix_name")),
        "concrete_type": _none_if_blank(data.get("concrete_type")),
        "color": _none_if_blank(data.get("color")),
        "fck28": _to_decimal(data.get("fck28")),
        "target_slump": _to_decimal(data.get("target_slump")),
        "cement_consumption": _to_decimal(data.get("cement_consumption")),
        "specific_mass": _to_decimal(data.get("specific_mass")),
    }

    materials = data.get("materials", []) or []
    quantities = data.get("quantities", []) or []

    with engine.begin() as conn:
        mix_id = conn.execute(mix_query, mix_params).scalar_one()

        if materials and quantities:
            rel_query = text("""
                INSERT INTO "TracoMaterial"
                    ("id_Traco", "id_MaterialEspecie", "Quantidade_unitaria")
                VALUES
                    (:mix_id, :material_id, :quantity);
            """)

            for material_id, quantity in zip(materials, quantities):
                material_id = _none_if_blank(material_id)
                quantity = _to_decimal(quantity)

                if material_id is None or quantity is None:
                    continue

                conn.execute(rel_query, {
                    "mix_id": mix_id,
                    "material_id": int(material_id),
                    "quantity": quantity,
                })

    return mix_id

# Adicione esta função ao final do arquivo models.py

# Em models.py

def get_mix_with_materials(mix_id):
    # 1. Busca os dados do Traço
    mix_query = """
        SELECT
            "id_Traco"                   AS id,
            "Nome"                       AS name,
            "TipoConcreto"               AS concrete_type,
            "Cor"                        AS color,
            "fck28_MPa"                  AS fck28,
            "SlumpAlvo_cm"              AS target_slump,
            "ConsumoCimento_kg_m3"       AS cement_consumption,
            "massaespecifica_real_kg_m3" AS specific_mass
        FROM "Traco"
        WHERE "id_Traco" = :mix_id;
    """
    mixes = execute_select_query(mix_query, {"mix_id": mix_id})
    if not mixes:
        return None

    mix = dict(mixes[0])
    cement_consumption = float(mix["cement_consumption"] or 0)
    real_density = float(mix["specific_mass"] or 0)

    # 2. Busca Materiais
    materials_query = """
        SELECT
            m."NomeComercial"            AS commercial_name,
            m."MarcaComercial"           AS brand,
            m.tipo_material              AS material_type,
            m."MassaEspecifica_g_cm3"    AS specific_mass,
            tm."Quantidade_unitaria"     AS ratio
        FROM "TracoMaterial" tm
        JOIN "MaterialEspecie" m ON m."id_MaterialEspecie" = tm."id_MaterialEspecie"
        WHERE tm."id_Traco" = :mix_id;
    """
    materials = [dict(mat) for mat in execute_select_query(materials_query, {"mix_id": mix_id})]

    # 3. Cálculos automáticos do Traço
    water_ratio = 0.0
    fine_aggregates_ratio = 0.0
    total_aggregates_ratio = 0.0
    total_consumption_kg = 0.0
    total_volume_m3 = 0.0

    for mat in materials:
        ratio = float(mat["ratio"] or 0)
        consumption = ratio * cement_consumption
        mat["consumption"] = round(consumption, 2)

        # Massa específica em kg/m³
        sp_mass_g_cm3 = float(mat["specific_mass"] or 0)
        sp_mass_kg_m3 = sp_mass_g_cm3 * 1000.0
        mat["specific_mass_kg_m3"] = round(sp_mass_kg_m3, 2)

        total_consumption_kg += consumption
        if sp_mass_kg_m3 > 0:
            total_volume_m3 += consumption / sp_mass_kg_m3

        # Identificação para Alpha e Água/Cimento
        mat_type = str(mat["material_type"]).lower()
        if "água" in mat_type or "agua" in mat_type:
            water_ratio += ratio
        elif "miúdo" in mat_type or "miudo" in mat_type or "areia" in mat_type:
            fine_aggregates_ratio += ratio
            total_aggregates_ratio += ratio
        elif "graúdo" in mat_type or "graudo" in mat_type or "brita" in mat_type:
            total_aggregates_ratio += ratio

    # Relação A/C
    mix["water_cement_ratio"] = round(water_ratio, 2) if water_ratio > 0 else "-"

    # Teor de Argamassa Alpha (%) = (1 + Areia) / (1 + Total Agregados) * 100
    if total_aggregates_ratio > 0:
        alpha = ((1.0 + fine_aggregates_ratio) / (1.0 + total_aggregates_ratio)) * 100.0
        mix["alpha"] = round(alpha, 2)
    else:
        mix["alpha"] = "-"

    # Massa Específica Teórica (kg/m³)
    if total_volume_m3 > 0:
        theoretical_density = total_consumption_kg / total_volume_m3
        mix["theoretical_density"] = round(theoretical_density, 2)
    else:
        mix["theoretical_density"] = "-"

    # Ar incorporado (m³/m³)
    if isinstance(mix["theoretical_density"], (int, float)) and real_density > 0:
        air_entrained = (1.0 - (real_density / mix["theoretical_density"]))
        mix["air_entrained"] = round(max(0.0, air_entrained), 4)
    else:
        mix["air_entrained"] = "-"

    mix["materials"] = materials
    return mix

# ==========================================================
# Concrete Productions
# ==========================================================

def list_concrete_productions():
    query = """
        SELECT
            p."id_Concreto"                        AS id,
            p."id_Traco"                            AS mix_id,
            t."Nome"                                 AS mix_name,
            p."DataProducao"                         AS production_date,
            p."SlumpProducao_cm"                     AS production_slump,
            p."fc28_MPa"                              AS fc28,
            p."Massa_especifica_fresca_kg_m3"        AS fresh_density
        FROM "ProducaoConcreto" p
        LEFT JOIN "Traco" t ON t."id_Traco" = p."id_Traco"
        ORDER BY p."DataProducao";
    """
    return execute_select_query(query)


def create_concrete_production(data):
    query = """
        INSERT INTO "ProducaoConcreto"
            ("id_Traco", "DataProducao", "SlumpProducao_cm", "fc28_MPa", "Massa_especifica_fresca_kg_m3")
        VALUES
            (:mix_id, :production_date, :production_slump, :fc28, :fresh_density)
        RETURNING "id_Concreto";
    """

    params = {
        "mix_id": int(data.get("mix_id")),
        "production_date": _none_if_blank(data.get("production_date")),
        "production_slump": _to_decimal(data.get("production_slump")),
        "fc28": _to_decimal(data.get("fc28")),
        "fresh_density": _to_decimal(data.get("fresh_density")),
    }

    return execute_insert_returning_id(query, params)


# ==========================================================
# Strength Samples
# ==========================================================

def list_strength_samples():
    query = """
        SELECT
            s."id_ConcretoAmostraResistencia"  AS id,
            s."id_Concreto"                      AS production_id,
            p."DataProducao"                     AS production_date,
            t."Nome"                              AS mix_name,
            s."numero_corpodeprova"              AS specimen_number,
            s."DataRompimento"                    AS test_date,
            s."Idade_dias"                         AS age_days,
            s."resistencia_compressao_mpa"        AS compressive_strength,
            s."tipo_cura"                          AS curing_type,
            s."diametro_corpodeprova_cm"          AS specimen_diameter,
            s."massa_corpodeprova_g"              AS specimen_mass
        FROM "ConcretoAmostraResistencia" s
        LEFT JOIN "ProducaoConcreto" p ON p."id_Concreto" = s."id_Concreto"
        LEFT JOIN "Traco" t ON t."id_Traco" = p."id_Traco"
        ORDER BY s."DataRompimento";
    """
    return execute_select_query(query)


def create_strength_sample(data):
    query = """
        INSERT INTO "ConcretoAmostraResistencia"
            (
                "id_Concreto",
                "numero_corpodeprova",
                "DataRompimento",
                "Idade_dias",
                "resistencia_compressao_mpa",
                "tipo_cura",
                "diametro_corpodeprova_cm",
                "massa_corpodeprova_g"
            )
        VALUES
            (
                :production_id,
                :specimen_number,
                :test_date,
                :age_days,
                :compressive_strength,
                :curing_type,
                :specimen_diameter,
                :specimen_mass
            )
        RETURNING "id_ConcretoAmostraResistencia";
    """

    params = {
        "production_id": int(data.get("production_id")),
        "specimen_number": _none_if_blank(data.get("specimen_number")),
        "test_date": _none_if_blank(data.get("test_date")),
        "age_days": int(data.get("age_days")) if _none_if_blank(data.get("age_days")) is not None else None,
        "compressive_strength": _to_decimal(data.get("compressive_strength")),
        "curing_type": data.get("curing_type") or [],
        "specimen_diameter": _none_if_blank(data.get("specimen_diameter")),
        "specimen_mass": _to_decimal(data.get("specimen_mass")),
    }

    return execute_insert_returning_id(query, params)


def get_specimen_diameters():
    query = """
        SELECT unnest(enum_range(NULL::"enum_diametro_corpodeprova_cm")) AS value;
    """
    rows = execute_select_query(query)
    return [row["value"] for row in rows] if rows else []


import os
import re
import shutil
import subprocess
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# Configuração do Jinja2 para LaTeX com filtro de escape de caracteres especiais
def _tex_escape(text):
    if not isinstance(text, str):
        return text
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textascendercentered{}',
        '\\': r'\textbackslash{}',
    }
    regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key=lambda item: -len(item))))
    return regex.sub(lambda match: conv[match.group()], text)

# Caminho base dos templates
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')

import io
import os
import base64
from datetime import datetime
from flask import render_template
from xhtml2pdf import pisa

def get_image_base64(image_path):
    """Converte uma imagem local em string Base64 para o HTML do xhtml2pdf."""
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode('utf-8')
            ext = image_path.split('.')[-1].lower()
            mime = "image/png" if ext == "png" else "image/jpeg"
            return f"data:{mime};base64,{encoded}"
    return ""

def generate_traco_pdf(mix_id, form_data, files_data, root_path):
    mix = get_mix_with_materials(mix_id)
    if not mix:
        return None, "Traço não encontrado."

    # Trata a data
    raw_date = form_data.get("doc_date")
    if raw_date:
        try:
            doc_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            doc_date = raw_date
    else:
        doc_date = datetime.now().strftime("%d/%m/%Y")

    # Lógica para tratar a logo (se enviada via formulário ou arquivo estático)
    logo_base64 = ""
    logo_file = files_data.get("logo") if files_data else None
    
    if logo_file and logo_file.filename:
        # Se o usuário enviou um arquivo de logo no formulário
        encoded = base64.b64encode(logo_file.read()).decode('utf-8')
        mime = logo_file.content_type or "image/png"
        logo_base64 = f"data:{mime};base64,{encoded}"
    else:
        # Se houver uma logo padrão na pasta static
        default_logo_path = os.path.join(root_path, "static", "images", "logo.png")
        logo_base64 = get_image_base64(default_logo_path)

    header_data = {
        "company": form_data.get("company", ""),
        "interested": form_data.get("interested", ""),
        "reference": form_data.get("reference", ""),
        "doc_date": doc_date,
        "logo_base64": logo_base64,
    }

    html_content = render_template("traco_pdf_template.html", mix=mix, header=header_data)

    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

    if pisa_status.err:
        return None, "Erro ao gerar o PDF."

    pdf_buffer.seek(0)
    return pdf_buffer, None

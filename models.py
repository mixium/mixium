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
# Emission Factors (FatorEmissaoMaterial)
# ==========================================================

def list_emission_factors(material_id=None, search=None):
    query = """
        SELECT
            f."id_FatorEmissao"      AS id,
            f."id_MaterialEspecie"   AS material_id,
            m."NomeComercial"        AS material_name,
            m."MarcaComercial"       AS material_brand,
            f."Valor_FatorEmissao"   AS value,
            f."Escopo"               AS scope,
            f."Fonte"                AS source,
            f."AnoReferencia"        AS reference_year,
            f."NormaReferencia"      AS reference_standard,
            f."Observacao"           AS notes
        FROM "FatorEmissaoMaterial" AS f
        JOIN "MaterialEspecie" AS m ON m."id_MaterialEspecie" = f."id_MaterialEspecie"
        WHERE (:material_id IS NULL OR f."id_MaterialEspecie" = :material_id)
          AND (
                :search IS NULL
                OR m."NomeComercial" ILIKE :search
                OR f."Fonte" ILIKE :search
                OR f."NormaReferencia" ILIKE :search
              )
        ORDER BY m."NomeComercial", f."AnoReferencia" DESC NULLS LAST;
    """

    params = {
        "material_id": int(material_id) if _none_if_blank(material_id) is not None else None,
        "search": f"%{search}%" if _none_if_blank(search) else None,
    }

    return execute_select_query(query, params) or []


def get_emission_factor(factor_id):
    query = """
        SELECT
            f."id_FatorEmissao"      AS id,
            f."id_MaterialEspecie"   AS material_id,
            m."NomeComercial"        AS material_name,
            f."Valor_FatorEmissao"   AS value,
            f."Escopo"               AS scope,
            f."Fonte"                AS source,
            f."AnoReferencia"        AS reference_year,
            f."NormaReferencia"      AS reference_standard,
            f."Observacao"           AS notes
        FROM "FatorEmissaoMaterial" AS f
        JOIN "MaterialEspecie" AS m ON m."id_MaterialEspecie" = f."id_MaterialEspecie"
        WHERE f."id_FatorEmissao" = :factor_id;
    """
    rows = execute_select_query(query, {"factor_id": factor_id})
    return dict(rows[0]) if rows else None


def create_emission_factor(data):
    query = """
        INSERT INTO "FatorEmissaoMaterial"
            ("id_MaterialEspecie", "Valor_FatorEmissao",
             "Fonte", "AnoReferencia", "NormaReferencia", "Observacao")
        VALUES
            (:material_id, :value,
             :source, :reference_year, :reference_standard, :notes)
        RETURNING "id_FatorEmissao";
    """

    params = {
        "material_id": int(data.get("material_id")),
        "value": _to_decimal(data.get("value")),
        "source": _none_if_blank(data.get("source")),
        "reference_year": int(data.get("reference_year"))
            if _none_if_blank(data.get("reference_year")) is not None else None,
        "reference_standard": _none_if_blank(data.get("reference_standard")),
        "notes": _none_if_blank(data.get("notes")),
    }

    return execute_insert_returning_id(query, params)


def calculate_cmat(materials, factor_selection=None):
    """
    Calcula a ACV parcial "Cmat" (kgCO2/m3 de concreto), conforme o boletim
    técnico do IBRACON, a partir do consumo de cada material do traço
    (kg/m3) e dos fatores de emissão máximo e mínimo escolhidos para cada
    material.

    materials: lista de materiais do traço (com "material_id", "commercial_name"
        e "consumption", no formato retornado por get_mix_with_materials).
    factor_selection: dict {material_id: {"factor_max_id": id ou None,
        "factor_min_id": id ou None}}.

    Retorna um dict com as linhas da tabela e os totais (Cmat máximo e mínimo).
    Materiais sem fator escolhido entram na tabela com emissão "-" e não
    somam nos totais.
    """
    factor_selection = factor_selection or {}
    rows = []
    total_max = 0.0
    total_min = 0.0

    for mat in materials:
        material_id = mat.get("material_id")
        consumption = float(mat.get("consumption") or 0)
        selection = factor_selection.get(material_id) or {}

        factor_max_id = _none_if_blank(selection.get("factor_max_id"))
        factor_min_id = _none_if_blank(selection.get("factor_min_id"))

        factor_max = get_emission_factor(int(factor_max_id)) if factor_max_id is not None else None
        factor_min = get_emission_factor(int(factor_min_id)) if factor_min_id is not None else None

        factor_max_value = float(factor_max["value"]) if factor_max and factor_max.get("value") is not None else None
        factor_min_value = float(factor_min["value"]) if factor_min and factor_min.get("value") is not None else None

        emission_max = consumption * factor_max_value if factor_max_value is not None else None
        emission_min = consumption * factor_min_value if factor_min_value is not None else None

        if emission_max is not None:
            total_max += emission_max
        if emission_min is not None:
            total_min += emission_min

        rows.append({
            "material_id": material_id,
            "material_name": mat.get("commercial_name"),
            "consumption": round(consumption, 2),
            "factor_max": round(factor_max_value, 6) if factor_max_value is not None else None,
            "factor_min": round(factor_min_value, 6) if factor_min_value is not None else None,
            "emission_max": round(emission_max, 3) if emission_max is not None else None,
            "emission_min": round(emission_min, 3) if emission_min is not None else None,
        })

    return {
        "rows": rows,
        "total_max": round(total_max, 3),
        "total_min": round(total_min, 3),
    }


# ==========================================================
# Mixes
# ==========================================================

def list_mixes():
    query = """
        SELECT
            t."id_Traco"                   AS id,
            t."Nome"                       AS name,
            t."TipoConcreto"               AS concrete_type,
            t."Cor"                        AS color,
            t."fckest28_MPa"              AS fckest28,
            t."SlumpAlvo_cm"              AS target_slump,
            t."ConsumoCimento_kg_m3"     AS cement_consumption,
            t."massaespecifica_real_kg_m3"    AS specific_mass,
            COALESCE(
                string_agg(
                    m."NomeComercial" || ' : ' || TRIM(TRAILING '0' FROM tm."Quantidade_unitaria"::text),
                    ' ; ' ORDER BY tm."Quantidade_unitaria" DESC
                ),
                'Sem composição'
            ) AS composition
        FROM "Traco" t
        LEFT JOIN "TracoMaterial" tm ON tm."id_Traco" = t."id_Traco"
        LEFT JOIN "MaterialEspecie" m ON m."id_MaterialEspecie" = tm."id_MaterialEspecie"
        GROUP BY t."id_Traco"
        ORDER BY t."Nome";
    """
    return execute_select_query(query)


def create_mix(data):
    engine = get_db()

    mix_query = text("""
        INSERT INTO "Traco"
            ("Nome", "TipoConcreto", "Cor", "fckest28_MPa", "SlumpAlvo_cm", "ConsumoCimento_kg_m3", "massaespecifica_real_kg_m3")
        VALUES
            (:mix_name, :concrete_type, :color, :fckest28, :target_slump, :cement_consumption, :specific_mass)
        RETURNING "id_Traco";
    """)

    mix_params = {
        "mix_name": _none_if_blank(data.get("mix_name")),
        "concrete_type": _none_if_blank(data.get("concrete_type")),
        "color": _none_if_blank(data.get("color")),
        "fckest28": _to_decimal(data.get("fckest28")),
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


def get_mix_with_materials(mix_id):
    # 1. Busca os dados do Traço
    mix_query = """
        SELECT
            "id_Traco"                   AS id,
            "Nome"                       AS name,
            "TipoConcreto"               AS concrete_type,
            "Cor"                        AS color,
            "fckest28_MPa"             AS fckest28,
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
            m."id_MaterialEspecie"       AS material_id,
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
            p."fcm28_MPa"                              AS fcm28,
            p."Massa_especifica_fresca_kg_m3"        AS fresh_density
        FROM "ProducaoConcreto" p
        LEFT JOIN "Traco" t ON t."id_Traco" = p."id_Traco"
        ORDER BY p."DataProducao";
    """
    return execute_select_query(query)


def create_concrete_production(data):
    query = """
        INSERT INTO "ProducaoConcreto"
            ("id_Traco", "DataProducao", "SlumpProducao_cm", "fcm28_MPa", "Massa_especifica_fresca_kg_m3")
        VALUES
            (:mix_id, :production_date, :production_slump, :fcm28, :fresh_density)
        RETURNING "id_Concreto";
    """

    params = {
        "mix_id": int(data.get("mix_id")),
        "production_date": _none_if_blank(data.get("production_date")),
        "production_slump": _to_decimal(data.get("production_slump")),
        "fcm28": _to_decimal(data.get("fcm28_MPa")),
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


def get_strength_sample(sample_id):
    query = """
        SELECT
            s."id_ConcretoAmostraResistencia"  AS id,
            s."id_Concreto"                    AS production_id,
            s."numero_corpodeprova"            AS specimen_number,
            s."DataRompimento"                 AS test_date,
            s."Idade_dias"                     AS age_days,
            s."resistencia_compressao_mpa"     AS compressive_strength,
            s."tipo_cura"                      AS curing_type,
            s."diametro_corpodeprova_cm"      AS specimen_diameter,
            s."massa_corpodeprova_g"          AS specimen_mass
        FROM "ConcretoAmostraResistencia" s
        WHERE s."id_ConcretoAmostraResistencia" = :id;
    """
    rows = execute_select_query(query, {"id": sample_id})
    return dict(rows[0]) if rows else None


def update_strength_sample(sample_id, data):
    query = """
        UPDATE "ConcretoAmostraResistencia"
        SET
            "numero_corpodeprova" = :specimen_number,
            "DataRompimento" = :test_date,
            "Idade_dias" = :age_days,
            "resistencia_compressao_mpa" = :compressive_strength,
            "tipo_cura" = :curing_type,
            "diametro_corpodeprova_cm" = :specimen_diameter,
            "massa_corpodeprova_g" = :specimen_mass
        WHERE "id_ConcretoAmostraResistencia" = :id;
    """

    params = {
        "id": int(sample_id),
        "specimen_number": _none_if_blank(data.get("specimen_number")),
        "test_date": _none_if_blank(data.get("test_date")),
        "age_days": int(data.get("age_days")) if _none_if_blank(data.get("age_days")) is not None else None,
        "compressive_strength": _to_decimal(data.get("compressive_strength")),
        "curing_type": data.get("curing_type") or None,
        "specimen_diameter": _none_if_blank(data.get("specimen_diameter")),
        "specimen_mass": _to_decimal(data.get("specimen_mass")),
    }

    return execute_modify_query(query, params)


# Generic delete helpers for main entities
def delete_material(material_id):
    query = 'DELETE FROM "MaterialEspecie" WHERE "id_MaterialEspecie" = :id;'
    return execute_modify_query(query, {"id": int(material_id)})


def delete_emission_factor(factor_id):
    query = 'DELETE FROM "FatorEmissaoMaterial" WHERE "id_FatorEmissao" = :id;'
    return execute_modify_query(query, {"id": int(factor_id)})


def delete_mix(mix_id):
    # Try removing the trace; DB foreign keys should take care of children if configured.
    query = 'DELETE FROM "Traco" WHERE "id_Traco" = :id;'
    return execute_modify_query(query, {"id": int(mix_id)})


def delete_concrete_production(production_id):
    query = 'DELETE FROM "ProducaoConcreto" WHERE "id_Concreto" = :id;'
    return execute_modify_query(query, {"id": int(production_id)})


def delete_strength_sample(sample_id):
    query = 'DELETE FROM "ConcretoAmostraResistencia" WHERE "id_ConcretoAmostraResistencia" = :id;'
    return execute_modify_query(query, {"id": int(sample_id)})


def get_specimen_diameters():
    query = """
        SELECT unnest(enum_range(NULL::"enum_diametro_corpodeprova_cm")) AS value;
    """
    rows = execute_select_query(query)
    return [row["value"] for row in rows] if rows else []


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

import io
from flask import render_template
from xhtml2pdf import pisa

def generate_traco_pdf(mix_id, form_data=None, factor_selection=None, files_data=None, root_path=None):
    # Se o primeiro argumento já for o objeto mix, usamos ele, senão buscamos pelo id
    if isinstance(mix_id, dict):
        mix = mix_id
    else:
        mix = get_mix_with_materials(mix_id)

    if not mix:
        return None, "Traço não encontrado."

    form_data = form_data or {}

    # ACV parcial "Cmat" (boletim técnico IBRACON): emissões máxima e mínima
    # de 1 m³ de concreto, a partir dos fatores de emissão escolhidos por material.
    mix["cmat"] = calculate_cmat(mix.get("materials", []), factor_selection)

    # O dicionário 'header' é enviado para o Jinja2 no template HTML do PDF
    header_data = {
        "company": form_data.get("company", ""),
        "interested": form_data.get("interested", ""),
        "reference": form_data.get("reference", ""),
        "doc_date": form_data.get("doc_date", ""),
        "logo_base64": form_data.get("logo_base64", "") # Passa a imagem convertida
    }

    # Renderiza o HTML com a chave 'header'
    html_content = render_template("traco_pdf_template.html", mix=mix, header=header_data)

    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

    if pisa_status.err:
        return None, "Erro ao gerar o PDF com xhtml2pdf."

    pdf_buffer.seek(0)
    return pdf_buffer, None
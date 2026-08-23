
from app import app
from models import *
import os
from flask import render_template, request, redirect, url_for, flash, send_file
import base64



# ==========================================================
# Home
# ==========================================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================================
# Materials
# ==========================================================

@app.route("/materials")
def materials():
    search = request.args.get("q") or None
    material_type = request.args.get("tipo") or None

    materials = list_materials(search=search, material_type=material_type)

    return render_template(
        "materiais_lista.html",
        materials=materials,
        material_types=get_material_types()
    )


@app.route("/materials/new", methods=["GET", "POST"])
def new_material():
    if request.method == "POST":
        MaterialEspecie = {
            "commercial_name": request.form["commercial_name"],
            "brand": request.form["brand"],
            "specific_mass": request.form["specific_mass"],
            "material_type": request.form["material_type"]
        }

        create_material(MaterialEspecie)
        flash("Material cadastrado com sucesso.")
        return redirect(url_for("materials"))

    return render_template(
        "materiais_form.html",
        form={},
        material_types=get_material_types()
    )


# ==========================================================
# Emission Factors
# ==========================================================

@app.route("/emission-factors")
def emission_factors():
    material_id = request.args.get("material_id") or None
    search = request.args.get("q") or None

    factors = list_emission_factors(material_id=material_id, search=search)

    return render_template(
        "fatores_emissao_lista.html",
        factors=factors,
        materials=list_materials(),
        selected_material=material_id,
        search=search or ""
    )


@app.route("/emission-factors/new", methods=["GET", "POST"])
def new_emission_factor():
    if request.method == "POST":
        FatorEmissaoMaterial = {
            "material_id": request.form["material_id"],
            "value": request.form["value"],
            "unit": request.form["unit"],
            "scope": request.form.get("scope"),
            "source": request.form.get("source"),
            "reference_year": request.form.get("reference_year"),
            "reference_standard": request.form.get("reference_standard"),
            "notes": request.form.get("notes"),
        }

        create_emission_factor(FatorEmissaoMaterial)
        flash("Fator de emissão cadastrado com sucesso.")
        return redirect(url_for("emission_factors"))

    return render_template(
        "fatores_emissao_form.html",
        form={},
        materials=list_materials(),
        scopes=get_emission_scopes()
    )


# ==========================================================
# Mixes
# ==========================================================

@app.route("/mixes")
def mixes():
    mixes = list_mixes()
    return render_template("tracos_lista.html", mixes=mixes)


@app.route("/mixes/new", methods=["GET", "POST"])
def new_mix():
    if request.method == "POST":
        Traco = {
            "mix_name": request.form["mix_name"],
            "concrete_type": request.form["concrete_type"],
            "color": request.form["color"],
            "fckest28_MPa": request.form["fckest28_MPa"],
            "target_slump": request.form["target_slump"],
            "cement_consumption": request.form["cement_consumption"],
            "specific_mass": request.form["specific_mass"],
            "materials": request.form.getlist("materials"),
            "quantities": request.form.getlist("quantities"),
        }
        create_mix(Traco)
        flash("Traço cadastrado com sucesso.")
        return redirect(url_for("mixes"))

    return render_template("tracos_form.html", form={}, materials=list_materials())


@app.route('/mixes/<int:mix_id>/pdf', methods=['GET', 'POST'])
def print_mix_pdf(mix_id):
    mix = get_mix_with_materials(mix_id)
    if not mix:
        flash("Traço não encontrado.", "danger")
        return redirect(url_for('mixes'))

    # GET: Abre o formulário traco_pdf_form.html
    if request.method == 'GET':
        return render_template('traco_pdf_form.html', mix=mix)

    # POST: Lê o arquivo 'logo' do formulário
    logo_file = request.files.get('logo')
    logo_base64 = ""

    if logo_file and logo_file.filename != '':
        image_bytes = logo_file.read()
        encoded = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = logo_file.mimetype or 'image/png'
        logo_base64 = f"data:{mime_type};base64,{encoded}"

    form_data = request.form.to_dict()
    form_payload = {
        "company": form_data.get("company", ""),
        "interested": form_data.get("interested", ""),
        "reference": form_data.get("reference", ""),
        "doc_date": form_data.get("doc_date", ""),
        "logo_base64": logo_base64
    }

    pdf_buffer, error = generate_traco_pdf(mix, form_data=form_payload)

    if error:
        flash(f"Erro ao gerar PDF: {error}", "danger")
        return redirect(url_for('print_mix_pdf', mix_id=mix_id))

    return send_file(
        pdf_buffer,
        as_attachment=False,
        mimetype='application/pdf',
        download_name=f'Carta_Traco_{mix_id}.pdf'
    )
    
# ==========================================================
# Concrete Productions
# ==========================================================

@app.route("/productions")
def productions():
    productions = list_concrete_productions()

    return render_template(
        "concretos_lista.html",
        productions=productions
    )

'''------------------------'''

@app.route("/productions/new", methods=["GET", "POST"])
def new_production():
    if request.method == "POST":
        ConcretoProducao = {
            "mix_id": request.form["mix_id"],
            "production_date": request.form["production_date"],
            "production_slump": request.form["production_slump"],
            "fcm28": request.form["fcm28"],
            "fresh_density": request.form["fresh_density"]
        }

        create_concrete_production(ConcretoProducao)

        flash("Produção cadastrada com sucesso.")
        return redirect(url_for("productions"))

    return render_template(
        "concretos_form.html",
        form={},  # <--- Adicionado prevendo a tela de produções
        mixes=list_mixes()
    )

# ==========================================================
# Strength Samples
# ==========================================================

@app.route("/strength-samples")
def strength_samples():
    samples = list_strength_samples()

    return render_template(
        "amostras_lista.html",
        samples=samples
    )



@app.route("/strength-samples/new", methods=["GET", "POST"])
def new_strength_sample():
    if request.method == "POST":
        ConcretoAmostraResistencia = {
            "production_id": request.form["production_id"],
            "specimen_number": request.form.get("specimen_number"),
            "test_date": request.form["test_date"],
            "age_days": request.form["age_days"],
            "compressive_strength": request.form["compressive_strength"],
            "curing_type": request.form.get("curing_type"),
            "specimen_diameter": request.form["specimen_diameter"],
            "specimen_mass": request.form["specimen_mass"]
        }

        create_strength_sample(ConcretoAmostraResistencia)

        flash("Corpo de prova cadastrado com sucesso.")
        return redirect(url_for("strength_samples"))

    return render_template(
        "amostras_form.html",
        form={},  # <--- Adicionado prevendo a tela de corpos de prova
        productions=list_concrete_productions(),
        diameters=get_specimen_diameters()
    )

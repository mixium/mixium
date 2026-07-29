
from app import app
from models import *
import os
from flask import render_template, request, redirect, url_for, flash, send_file



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
            "fck28": request.form["fck28"],
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


@app.route("/mixes/<int:mix_id>/pdf", methods=["GET", "POST"])
def print_mix_pdf(mix_id):
    mix = get_mix_with_materials(mix_id)
    if not mix:
        flash("Traço não encontrado.")
        return redirect(url_for("mixes"))

    # GET: Exibe o formulário para preencher os dados do cabeçalho / logo
    if request.method == "GET":
        return render_template("traco_pdf_form.html", mix=mix)

    # POST: Delega a geração do arquivo para a regra de negócio em models.py
    pdf_path, error = generate_traco_pdf(
        mix_id=mix_id,
        form_data=request.form,
        files_data=request.files,
        root_path=app.root_path
    )

    if error or not pdf_path:
        flash(f"Erro ao gerar PDF: {error}")
        return redirect(url_for("mixes"))

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"Carta_Traco_{mix['name']}.pdf"
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
            "fc28": request.form["fc28"],
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


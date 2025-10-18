from flask import Flask, request, render_template_string, make_response
import ee
import folium
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io

ee.Initialize()
app = Flask(__name__)

@app.route('/')
def index():
    years = list(range(2018, 2026))
    year_start = request.args.get('year_start')
    year_end = request.args.get('year_end')
    selected_district = request.args.get('district')

    all_boundaries = ee.FeatureCollection('projects/nairaproject/assets/Al_Qualyubiyah')
    district_names = all_boundaries.aggregate_array("NAME_2").distinct().getInfo()
    district_names = [d for d in district_names if d != "Unorganized in Al Qalyubiyah"]
    district_names.insert(0, "محافظة القليوبية")

    roi = all_boundaries if not selected_district or selected_district == "محافظة القليوبية" \
        else all_boundaries.filter(ee.Filter.eq("NAME_2", selected_district))

    map_center = roi.geometry().centroid().coordinates().getInfo()[::-1]
    fmap = folium.Map(location=map_center, zoom_start=11, height='600px')

    style = {'color': 'black', 'fillColor': '00000000', 'weight': 1}
    folium.GeoJson(data=roi.getInfo(), name='حدود محافظة القليوبية', style_function=lambda x: style).add_to(fmap)

    ratios = None

    if year_start and year_end:
        year_start, year_end = int(year_start), int(year_end)
        if year_start < year_end:
            def add_indices(image):
                ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
                evi = image.expression(
                    '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))', {
                        'NIR': image.select('B8'),
                        'RED': image.select('B4'),
                        'BLUE': image.select('B2')
                    }).rename('EVI')
                return image.addBands([ndvi, evi])

            def load_image(year):
                return ee.ImageCollection('COPERNICUS/S2_SR') \
                    .filterBounds(roi) \
                    .filterDate(f'{year}-01-01', f'{year}-01-31') \
                    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 4)) \
                    .map(add_indices) \
                    .select(['NDVI', 'EVI']) \
                    .mean().clip(roi)

            img_start = load_image(year_start)
            img_end = load_image(year_end)

            crop_start = img_start.select('NDVI').gte(0.3).And(img_start.select('EVI').gte(0.2))
            crop_end = img_end.select('NDVI').gte(0.3).And(img_end.select('EVI').gte(0.2))

            stable = crop_start.And(crop_end)
            degraded = crop_start.And(crop_end.Not())

            degraded_mapid = degraded.updateMask(degraded).getMapId({'palette': ['#d62828']})
            folium.TileLayer(
                tiles=degraded_mapid['tile_fetcher'].url_format,
                attr='Degraded Areas',
                name=f'الاراضي الزراعية المتدهورة ({year_start} → {year_end})',
                overlay=True
            ).add_to(fmap)

            stable_mapid = stable.updateMask(stable).getMapId({'palette': ['#198754']})
            folium.TileLayer(
                tiles=stable_mapid['tile_fetcher'].url_format,
                attr='Stable Cropland',
                name=f'الاراضي الزراعية االمستقرة ({year_start} → {year_end})',
                overlay=True
            ).add_to(fmap)

            pixel_area = ee.Image.pixelArea()

            area_total = crop_start.multiply(pixel_area).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi.geometry(), scale=10, maxPixels=1e13).get('NDVI')

            area_degraded = degraded.multiply(pixel_area).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi.geometry(), scale=10, maxPixels=1e13).get('NDVI')

            area_stable = stable.multiply(pixel_area).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi.geometry(), scale=10, maxPixels=1e13).get('NDVI')

            val_total = ee.Number(area_total).getInfo() / 1e6
            val_deg = ee.Number(area_degraded).getInfo() / 1e6
            val_stable = ee.Number(area_stable).getInfo() / 1e6

            ratios = {
                'total': round(val_total, 2),
                'degraded': round(val_deg, 2),
                'stable': round(val_stable, 2),
                'degradation_percent': round((val_deg / val_total) * 100, 2) if val_total > 0 else 0
            }

    folium.LayerControl().add_to(fmap)
    map_html = fmap._repr_html_()

    return render_template_string("""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>تحليل الأراضي الزراعية</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            font-family: 'Segoe UI', sans-serif;
            background-color: #f4f6f9;
            margin: 0;
            padding: 0;
        }
        h2 {
            font-weight: bold;
            color: #146c43;
            margin-top: 20px;
        }
        .header-form {
            background: #e9ecef;
            padding: 20px;
            display: flex;
            gap: 15px;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            border-bottom: 2px solid #dee2e6;
        }
        .header-form label {
            font-weight: bold;
            color: #495057;
            margin-bottom: 5px;
        }
        .header-form select, .header-form button {
            max-width: 200px;
            min-width: 150px;
        }
        .main-container {
            display: flex;
            flex-direction: row;
            height: calc(100vh - 100px);
        }
        .sidebar {
            width: 25%;
            background: #ffffff;
            padding: 25px;
            overflow-y: auto;
            border-left: 2px solid #dee2e6;
            box-shadow: inset 0 0 10px rgba(0,0,0,0.03);
        }
        .sidebar p {
            font-size: 0.95rem;
            color: #333;
            margin-bottom: 8px;
        }
        .sidebar .btn {
            font-weight: bold;
        }
        .map-container {
            width: 75%;
            padding: 20px;
        }

    </style>
</head>
<body>
    <h2 class="text-center">التحليل الزمني للأراضي الزراعية في محافظة القليوبية</h2>
    <form method="get" class="header-form">
        <label>سنة البداية:</label>
        <select name="year_start" class="form-select">
            {% for y in years %}
                <option value="{{ y }}" {% if y|string == request.args.get('year_start') %}selected{% endif %}>{{ y }}</option>
            {% endfor %}
        </select>

        <label>سنة النهاية:</label>
        <select name="year_end" class="form-select">
            {% for y in years %}
                <option value="{{ y }}" {% if y|string == request.args.get('year_end') %}selected{% endif %}>{{ y }}</option>
            {% endfor %}
        </select>

        <label>اختر المركز:</label>
        <select name="district" class="form-select">
            {% for d in districts %}
                <option value="{{ d }}" {% if d == request.args.get('district') %}selected{% endif %}>{{ d }}</option>
            {% endfor %}
        </select>

        <button type="submit" class="btn btn-success fw-bold">تحليل</button>
    </form>

    <div class="main-container">
        <div class="sidebar">
            {% if ratios %}
                <p><strong>المنطقة:</strong> {{ request.args.get('district') or 'محافظة القليوبية' }}</p>
                <p><strong>اجمالي الاراضي الزراعية:</strong> {{ ratios.total }} كم²</p>
                <p><strong>الاراضي المستقرة:</strong> {{ ratios.stable }} كم²</p>
                <p><strong>الاراضي المتدهورة:</strong> {{ ratios.degraded }} كم²</p>
                <p><strong>نسبة التدهور:</strong> {{ ratios.degradation_percent }}%</p>
                <canvas id="landChart" width="800" height="900"></canvas>
                <a class="btn btn-outline-success mt-3 w-100 fw-bold" href="/download_pdf?district={{ request.args.get('district') or 'محافظة القليوبية' }}&ys={{ year_start }}&ye={{ year_end }}&t={{ ratios.total }}&s={{ ratios.stable }}&d={{ ratios.degraded }}&p={{ ratios.degradation_percent }}">
            تحميل النتائج كـ PDF
            </a>
            {% endif %}
        </div>

        <div class="map-container">
            {{ map_html|safe }}
        </div>
    </div>

    {% if ratios %}
    <script>
        const ctx = document.getElementById('landChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['اجمالي', 'متدهورة', 'مستقرة'],
                datasets: [{
                    label: 'كم²',
                    data: [{{ ratios.total }}, {{ ratios.degraded }}, {{ ratios.stable }}],
                    backgroundColor: ['#0d6efd', '#d62828', '#198754']
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: context => context.parsed.y + ' كم²'
                        }
                    }
                },
                scales: { y: { beginAtZero: true } }
            }
        });
    </script>
    {% endif %}

</body>
</html>
""", map_html=map_html, years=years, districts=district_names, ratios=ratios,
    year_start=year_start, year_end=year_end)

@app.route('/download_pdf')
def download_pdf():
    district = request.args.get('district')
    year_start = request.args.get('ys')
    year_end = request.args.get('ye')
    total = request.args.get('t')
    stable = request.args.get('s')
    degraded = request.args.get('d')
    percent = request.args.get('p')

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)

    text = p.beginText(50, 800)
    text.setFont("Helvetica", 12)

    text.textLine(f"تحليل الأراضي الزراعية من {year_start} إلى {year_end}")
    text.textLine(f"المنطقة: {district}")
    text.textLine(f"إجمالي الأراضي الزراعية: {total} كم²")
    text.textLine(f"الأراضي المستقرة: {stable} كم²")
    text.textLine(f"الأراضي المتدهورة: {degraded} كم²")
    text.textLine(f"نسبة التدهور: {percent}%")

    p.drawText(text)
    p.showPage()
    p.save()

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers["Content-Disposition"] = "attachment; filename=analysis_result.pdf"
    response.headers["Content-type"] = "application/pdf"
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8500)



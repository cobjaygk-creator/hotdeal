from app.amazon_jp.mottoku import parse_list
from app.amazon_jp.pipeline import amazon_product_url


SAMPLE = """
<div class="deal-card-wrap">
  <a href="/a/B0GVSMPQT6?s=mtk" class="deal-card">
    <div class="deal-card-image">
      <span class="deal-card-badge badge-amazon">Amazon</span>
      <span class="deal-card-discount">-94%</span>
      <img src="https://m.media-amazon.com/images/I/31AEaoVuUjL._SL500_.jpg" alt="">
    </div>
    <div class="deal-card-body">
      <h3 class="deal-card-name">ワイヤレスイヤホン Bluetooth</h3>
      <p class="deal-card-price">
        <span class="deal-card-original">¥29,000</span>
        <span class="deal-card-current">¥1,699</span>
      </p>
      <p class="deal-card-updated">2026/09/02 03:39:57</p>
    </div>
  </a>
  <button type="button" class="deal-card-fav"
          data-fav-path="/a/B0GVSMPQT6"
          data-fav-source="amazon"
          data-fav-name="ワイヤレスイヤホン Bluetooth"
          data-fav-image="https://m.media-amazon.com/images/I/31AEaoVuUjL._SL500_.jpg"
          data-fav-price="1699"></button>
</div>
<div class="deal-card-wrap">
  <a href="/a/B095K7FYBK?s=mtk" class="deal-card">
    <div class="deal-card-image">
      <span class="deal-card-badge badge-amazon">Amazon</span>
      <span class="deal-card-discount">-94%</span>
    </div>
    <div class="deal-card-body">
      <h3 class="deal-card-name">安い本</h3>
      <span class="deal-card-current">¥99</span>
    </div>
  </a>
  <button type="button" class="deal-card-fav"
          data-fav-path="/a/B095K7FYBK"
          data-fav-source="amazon"
          data-fav-name="安い本"
          data-fav-price="99"></button>
</div>
<div class="deal-card-wrap">
  <a href="/a/B00TENPCT0?s=mtk" class="deal-card">
    <div class="deal-card-image">
      <span class="deal-card-badge badge-amazon">Amazon</span>
      <span class="deal-card-discount">-10%</span>
    </div>
    <div class="deal-card-body">
      <h3 class="deal-card-name">少しだけ安い</h3>
      <span class="deal-card-current">¥2,000</span>
    </div>
  </a>
  <button type="button" class="deal-card-fav"
          data-fav-path="/a/B00TENPCT0"
          data-fav-source="amazon"
          data-fav-price="2000"></button>
</div>
<div class="deal-card-wrap">
  <a href="/a/B0RAKUTEN1?s=mtk" class="deal-card">
    <div class="deal-card-image">
      <span class="deal-card-badge badge-rakuten">楽天市場</span>
      <span class="deal-card-discount">-50%</span>
    </div>
    <div class="deal-card-body">
      <h3 class="deal-card-name">楽天の商品</h3>
      <span class="deal-card-current">¥3,000</span>
    </div>
  </a>
  <button type="button" class="deal-card-fav"
          data-fav-path="/a/B0RAKUTEN1"
          data-fav-source="rakuten"
          data-fav-price="3000"></button>
</div>
<div class="deal-card-wrap">
  <a href="/a/B08CHARG01?s=mtk" class="deal-card">
    <div class="deal-card-image">
      <span class="deal-card-badge badge-amazon">Amazon</span>
      <span class="deal-card-discount">-32%</span>
      <img src="https://m.media-amazon.com/images/I/example.jpg" alt="">
    </div>
    <div class="deal-card-body">
      <h3 class="deal-card-name">Anker 充電器</h3>
      <p class="deal-card-price">
        <span class="deal-card-original">¥3,980</span>
        <span class="deal-card-current">¥2,680</span>
      </p>
    </div>
  </a>
  <button type="button" class="deal-card-fav"
          data-fav-path="/a/B08CHARG01"
          data-fav-source="amazon"
          data-fav-name="Anker 充電器"
          data-fav-image="https://m.media-amazon.com/images/I/example.jpg"
          data-fav-price="2680"></button>
</div>
"""


def test_mottoku_keeps_amazon_super_deals_only():
    deals = parse_list(SAMPLE)
    asins = {d.asin for d in deals}
    assert asins == {"B0GVSMPQT6", "B08CHARG01"}
    earbuds = next(d for d in deals if d.asin == "B0GVSMPQT6")
    assert earbuds.yen_price == 1699
    assert earbuds.original_yen == 29000
    assert earbuds.discount_rate == 0.94
    assert earbuds.image_url.endswith(".jpg")
    assert earbuds.source == "mottoku"
    charger = next(d for d in deals if d.asin == "B08CHARG01")
    assert charger.discount_rate == 0.32
    assert charger.yen_price == 2680


def test_amazon_product_url():
    assert amazon_product_url("B0GVSMPQT6") == "https://www.amazon.co.jp/dp/B0GVSMPQT6"

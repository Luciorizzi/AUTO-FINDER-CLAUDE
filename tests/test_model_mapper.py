"""Tests para el model mapper."""

from app.config import load_model_aliases
from app.parsers.model_mapper import ModelMapper


def _make_mapper(allow_ambiguous: bool = False) -> ModelMapper:
    """Crea un mapper con la config real del proyecto."""
    config = load_model_aliases()
    return ModelMapper(config, allow_ambiguous=allow_ambiguous)


class TestModelMapperHighConfidence:
    """Tests de matching con aliases exactos (confianza alta)."""

    def test_gol_trend_full(self):
        mapper = _make_mapper()
        result = mapper.match(title="Volkswagen Gol Trend 1.6 Pack I 2012")
        assert result.model_normalized == "Gol Trend"
        assert result.confidence == "high"

    def test_gol_trend_trendline(self):
        mapper = _make_mapper()
        result = mapper.match(title="Gol Trend Trendline 1.6 101cv")
        assert result.model_normalized == "Gol Trend"
        assert result.confidence == "high"

    def test_vw_gol(self):
        mapper = _make_mapper()
        result = mapper.match(title="VW Gol Trend 2013 75000 km")
        assert result.model_normalized == "Gol Trend"

    def test_clio_mio(self):
        mapper = _make_mapper()
        result = mapper.match(title="Renault Clio Mio 2014 87000 km")
        assert result.model_normalized == "Clio Mio"
        assert result.confidence == "high"

    def test_clio_mio_confort(self):
        mapper = _make_mapper()
        result = mapper.match(title="Clio Mio Confort 1.2 3p")
        assert result.model_normalized == "Clio Mio"

    def test_fiat_punto_attractive(self):
        mapper = _make_mapper()
        result = mapper.match(title="Fiat Punto Attractive 1.4 2015")
        assert result.model_normalized == "Fiat Punto"

    def test_punto_elx(self):
        mapper = _make_mapper()
        result = mapper.match(title="Punto ELX 1.4 Full 2012")
        assert result.model_normalized == "Fiat Punto"

    def test_ford_ka_fly(self):
        mapper = _make_mapper()
        result = mapper.match(title="Ford Ka Fly Viral 2013 102000 km")
        assert result.model_normalized == "Ford Ka"
        assert result.confidence == "high"

    def test_ka_viral(self):
        mapper = _make_mapper()
        result = mapper.match(title="Ka Viral 1.0 2011")
        assert result.model_normalized == "Ford Ka"

    def test_chevrolet_celta_lt(self):
        mapper = _make_mapper()
        result = mapper.match(title="Chevrolet Celta LT 2011 108000 km")
        assert result.model_normalized == "Chevrolet Celta"

    def test_celta_ls(self):
        mapper = _make_mapper()
        result = mapper.match(title="Celta LS 1.4 5p 2010")
        assert result.model_normalized == "Chevrolet Celta"

    def test_volkswagen_gol_full_noise(self):
        mapper = _make_mapper()
        result = mapper.match(title="volkswagen gol trend 1.6 pack i 101cv 3p")
        assert result.model_normalized == "Gol Trend"


class TestModelMapperAmbiguous:
    """Tests de matching con aliases ambiguos."""

    def test_clio_solo_no_match_default(self):
        """'clio' solo no deberia matchear sin allow_ambiguous."""
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Clio 1.2 Authentique 2014")
        assert result.model_normalized is None

    def test_clio_solo_matches_with_ambiguous(self):
        """'clio' solo deberia matchear con allow_ambiguous=True."""
        mapper = _make_mapper(allow_ambiguous=True)
        result = mapper.match(title="Clio 1.2 Authentique 2014")
        assert result.model_normalized == "Clio Mio"
        assert result.confidence == "low"

    def test_renault_clio_matches_medium(self):
        """'renault clio' matchea con confianza media (brand en titulo)."""
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Renault Clio 1.2 2013")
        assert result.model_normalized == "Clio Mio"
        assert result.confidence == "medium"

    def test_gol_solo_no_match_default(self):
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Gol 1.6 2010")
        assert result.model_normalized is None

    def test_volkswagen_gol_matches_medium(self):
        """'volkswagen gol' matchea con confianza media."""
        mapper = _make_mapper(allow_ambiguous=False)
        # "volkswagen gol" esta en los aliases exactos
        result = mapper.match(title="Volkswagen Gol 1.6 2010")
        assert result.model_normalized == "Gol Trend"

    def test_ka_solo_no_match_default(self):
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Ka 1.0 2011")
        assert result.model_normalized is None

    def test_ford_ka_brand_in_title(self):
        """'ford ka' es alias exacto -> match alto."""
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Ford Ka 1.0 2012")
        assert result.model_normalized == "Ford Ka"
        assert result.confidence == "high"


class TestModelMapperNoMatch:
    """Tests donde no deberia haber match."""

    def test_unknown_model(self):
        mapper = _make_mapper()
        result = mapper.match(title="Toyota Corolla 2015 50000 km")
        assert result.model_normalized is None
        assert result.confidence == "none"

    def test_empty_title(self):
        mapper = _make_mapper()
        result = mapper.match(title="")
        assert result.model_normalized is None

    def test_none_title(self):
        mapper = _make_mapper()
        result = mapper.match(title=None)
        assert result.model_normalized is None

    def test_random_text(self):
        mapper = _make_mapper()
        result = mapper.match(title="Repuesto para auto 2013")
        assert result.model_normalized is None


class TestModelMapperWithBrandField:
    """Tests donde se pasa brand como campo separado."""

    def test_brand_reinforces_ambiguous(self):
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Celta 1.4 2011", brand="Chevrolet")
        assert result.model_normalized == "Chevrolet Celta"
        assert result.confidence == "medium"

    def test_brand_reinforces_ka(self):
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Ka 1.0 Fly", brand="Ford")
        assert result.model_normalized == "Ford Ka"

    def test_wrong_brand_no_false_match(self):
        """Brand incorrecta no deberia forzar match."""
        mapper = _make_mapper(allow_ambiguous=False)
        result = mapper.match(title="Ka 1.0 2012", brand="Toyota")
        assert result.model_normalized is None

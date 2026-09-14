from pipeline.clustering import cluster_stories
from providers.base import NormalizedArticle


def make_article(**overrides):
    defaults = dict(article_id="1", title="Title", url="https://example.com/a", provider="p", source_name="Source")
    defaults.update(overrides)
    return NormalizedArticle(**defaults)


def test_cluster_stories_groups_related_articles_from_different_sources():
    a1 = make_article(
        title="India announces new semiconductor policy",
        description="India's government unveiled a new policy to boost semiconductor manufacturing.",
        url="https://a.example.com/1", source_name="Reuters",
    )
    a2 = make_article(
        title="Government unveils semiconductor manufacturing policy",
        description="India's cabinet approved a new semiconductor manufacturing policy today.",
        url="https://b.example.com/2", source_name="The Hindu",
    )
    a3 = make_article(
        title="Local team wins regional cricket tournament",
        description="A thrilling final saw the home team lift the trophy.",
        url="https://c.example.com/3", source_name="ESPN",
    )
    story_map = cluster_stories([a1, a2, a3], threshold=0.2)

    assert len(story_map) == 2
    assert a1.story_id == a2.story_id
    assert a3.story_id != a1.story_id


def test_cluster_stories_skips_duplicates():
    a1 = make_article(title="Story A", url="https://a.example.com/1")
    a2 = make_article(title="Story A duplicate", url="https://b.example.com/2")
    a2.is_duplicate = True

    story_map = cluster_stories([a1, a2])

    assert sum(len(v) for v in story_map.values()) == 1
    assert a2.story_id is None


def test_cluster_stories_empty_input():
    assert cluster_stories([]) == {}


def test_cluster_stories_unrelated_articles_stay_separate():
    a1 = make_article(title="Nvidia earnings beat expectations", url="https://a.example.com/1")
    a2 = make_article(title="Federal Reserve holds interest rates steady", url="https://b.example.com/2")
    story_map = cluster_stories([a1, a2])
    assert len(story_map) == 2

"""HTTP-layer tests for the teacher question-bank endpoints.

Covers:
- list: global catalog visible to any teacher; disabled hidden; private only to owner
- scope filter (catalog | mine | all) and content filters (subject/chapter/difficulty/q)
- facets (subjects / chapters / topics)
- private CRUD: create (mcq + short_answer), validation, update/delete own only
- cross-tenant isolation + admin token rejected
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.services import issue_tokens_for_user
from apps.exams.models import BankQuestion
from apps.people.tests.factories import TeacherFactory

URL = "/api/v1/teacher/question-bank"


def _auth(user) -> dict:  # type: ignore[no-untyped-def]
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_tokens_for_user(user)['access_token']}"}


def _teacher(world: dict):  # type: ignore[no-untyped-def]
    return TeacherFactory(school=world["school"], user=world["teacher_user"])


def _global_mcq(**kw) -> BankQuestion:  # type: ignore[no-untyped-def]
    defaults = {
        "school": None,
        "created_by": None,
        "source_id": "ps-ch1-mcq-01",
        "subject": "Physical Science",
        "grade": 8,
        "chapter_number": 1,
        "chapter_name": "Force",
        "topic": "What is Force",
        "question_type": "mcq",
        "difficulty": "easy",
        "text": "A force is a:",
        "options": [
            {"text": "Energy", "is_correct": False},
            {"text": "Push only", "is_correct": False},
            {"text": "Pull only", "is_correct": False},
            {"text": "Push or a pull", "is_correct": True},
        ],
        "explanation": "Force is a push or a pull.",
        "tags": ["force"],
    }
    defaults.update(kw)
    return BankQuestion.objects.create(**defaults)


def _private_q(teacher, **kw) -> BankQuestion:  # type: ignore[no-untyped-def]
    defaults = {
        "school": teacher.school,
        "created_by": teacher,
        "subject": "Physical Science",
        "question_type": "short_answer",
        "difficulty": "medium",
        "text": "Force is a push or a ___.",
        "correct_answer": "pull",
    }
    defaults.update(kw)
    return BankQuestion.objects.create(**defaults)


# ---------------------------------------------------------------------------
# List / visibility
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_list_shows_global_catalog(client: Client, world_a) -> None:
    _teacher(world_a)
    _global_mcq()
    res = client.get(URL, **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["scope"] == "catalog"
    assert item["questionType"] == "mcq"
    assert len(item["options"]) == 4
    assert item["sourceId"] == "ps-ch1-mcq-01"


@pytest.mark.django_db
def test_list_hides_disabled(client: Client, world_a) -> None:
    _teacher(world_a)
    _global_mcq(enabled=False)
    body = client.get(URL, **_auth(world_a["teacher_user"])).json()
    assert body["total"] == 0


@pytest.mark.django_db
def test_private_question_visible_only_to_owner(client: Client, world_a, world_b) -> None:
    teacher_a = _teacher(world_a)
    _teacher(world_b)
    _private_q(teacher_a, text="A's private question")

    own = client.get(URL, **_auth(world_a["teacher_user"])).json()
    assert own["total"] == 1
    assert own["items"][0]["scope"] == "mine"

    other = client.get(URL, **_auth(world_b["teacher_user"])).json()
    assert other["total"] == 0


@pytest.mark.django_db
def test_global_visible_across_tenants(client: Client, world_a, world_b) -> None:
    _teacher(world_a)
    _teacher(world_b)
    _global_mcq()
    assert client.get(URL, **_auth(world_a["teacher_user"])).json()["total"] == 1
    assert client.get(URL, **_auth(world_b["teacher_user"])).json()["total"] == 1


@pytest.mark.django_db
def test_scope_filter(client: Client, world_a) -> None:
    teacher = _teacher(world_a)
    _global_mcq()
    _private_q(teacher)
    auth = _auth(world_a["teacher_user"])

    assert client.get(URL, **auth).json()["total"] == 2
    assert client.get(f"{URL}?scope=catalog", **auth).json()["total"] == 1
    mine = client.get(f"{URL}?scope=mine", **auth).json()
    assert mine["total"] == 1 and mine["items"][0]["scope"] == "mine"


@pytest.mark.django_db
def test_content_filters(client: Client, world_a) -> None:
    _teacher(world_a)
    _global_mcq(source_id="g1", subject="Physical Science", chapter_name="Force", difficulty="easy")
    _global_mcq(
        source_id="g2", subject="Physical Science", chapter_name="Friction",
        difficulty="hard", text="Friction opposes motion.",
    )
    _global_mcq(source_id="g3", subject="Maths", chapter_name="Algebra", difficulty="easy")
    auth = _auth(world_a["teacher_user"])

    assert client.get(f"{URL}?subject=physical science", **auth).json()["total"] == 2
    assert client.get(f"{URL}?subject=Physical Science&chapter=Fric", **auth).json()["total"] == 1
    assert client.get(f"{URL}?difficulty=easy", **auth).json()["total"] == 2
    assert client.get(f"{URL}?q=friction", **auth).json()["total"] == 1


@pytest.mark.django_db
def test_facets(client: Client, world_a) -> None:
    _teacher(world_a)
    _global_mcq(source_id="g1", chapter_number=1, chapter_name="Force", topic="What is Force")
    _global_mcq(source_id="g2", chapter_number=2, chapter_name="Friction", topic="Drag")
    res = client.get(f"{URL}/facets?subject=Physical Science", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    body = res.json()
    assert body["subjects"] == ["Physical Science"]
    assert [c["name"] for c in body["chapters"]] == ["Force", "Friction"]
    assert set(body["topics"]) == {"What is Force", "Drag"}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_mcq(client: Client, world_a) -> None:
    _teacher(world_a)
    payload = {
        "subject": "Physical Science",
        "questionType": "mcq",
        "text": "What is the SI unit of force?",
        "difficulty": "easy",
        "chapterName": "Force",
        "options": [
            {"text": "Newton", "isCorrect": True},
            {"text": "Joule", "isCorrect": False},
            {"text": "Watt", "isCorrect": False},
            {"text": "Pascal", "isCorrect": False},
        ],
    }
    res = client.post(URL, data=payload, content_type="application/json", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["scope"] == "mine"
    assert body["sourceId"] == ""
    bq = BankQuestion.objects.get(id=body["id"])
    assert bq.created_by_id is not None and bq.school_id == world_a["school"].id


@pytest.mark.django_db
def test_create_short_answer(client: Client, world_a) -> None:
    _teacher(world_a)
    payload = {
        "subject": "Physical Science",
        "questionType": "short_answer",
        "text": "Force is a push or a ___.",
        "correctAnswer": "pull",
    }
    res = client.post(URL, data=payload, content_type="application/json", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200, res.content
    assert res.json()["correctAnswer"] == "pull"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload,msg",
    [
        ({"subject": "PS", "questionType": "mcq", "text": "Q", "options": [
            {"text": "a", "isCorrect": True}, {"text": "b", "isCorrect": False},
        ]}, "4 options"),
        ({"subject": "PS", "questionType": "mcq", "text": "Q", "options": [
            {"text": "a", "isCorrect": True}, {"text": "b", "isCorrect": True},
            {"text": "c", "isCorrect": False}, {"text": "d", "isCorrect": False},
        ]}, "one option"),
        ({"subject": "PS", "questionType": "short_answer", "text": "Q"}, "correct_answer"),
        ({"subject": "", "questionType": "short_answer", "text": "Q", "correctAnswer": "x"}, "Subject"),
    ],
)
def test_create_validation(client: Client, world_a, payload, msg) -> None:
    _teacher(world_a)
    res = client.post(URL, data=payload, content_type="application/json", **_auth(world_a["teacher_user"]))
    assert res.status_code == 422, res.content
    assert msg.lower() in res.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_update_own(client: Client, world_a) -> None:
    teacher = _teacher(world_a)
    bq = _private_q(teacher)
    payload = {
        "subject": "Physical Science",
        "questionType": "short_answer",
        "text": "Updated text?",
        "correctAnswer": "force",
    }
    res = client.patch(
        f"{URL}/{bq.id}", data=payload, content_type="application/json", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 200, res.content
    bq.refresh_from_db()
    assert bq.text == "Updated text?" and bq.correct_answer == "force"


@pytest.mark.django_db
def test_cannot_update_global(client: Client, world_a) -> None:
    _teacher(world_a)
    bq = _global_mcq()
    payload = {"subject": "PS", "questionType": "short_answer", "text": "x", "correctAnswer": "y"}
    res = client.patch(
        f"{URL}/{bq.id}", data=payload, content_type="application/json", **_auth(world_a["teacher_user"])
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_cannot_touch_other_teachers_question(client: Client, world_a, world_b) -> None:
    teacher_a = _teacher(world_a)
    _teacher(world_b)
    bq = _private_q(teacher_a)
    res = client.delete(f"{URL}/{bq.id}", **_auth(world_b["teacher_user"]))
    assert res.status_code == 404
    assert BankQuestion.objects.filter(id=bq.id).exists()


@pytest.mark.django_db
def test_delete_own(client: Client, world_a) -> None:
    teacher = _teacher(world_a)
    bq = _private_q(teacher)
    res = client.delete(f"{URL}/{bq.id}", **_auth(world_a["teacher_user"]))
    assert res.status_code == 200
    assert not BankQuestion.objects.filter(id=bq.id).exists()


@pytest.mark.django_db
def test_admin_token_rejected(client: Client, world_a) -> None:
    _teacher(world_a)
    res = client.get(URL, **_auth(world_a["admin"]))
    assert res.status_code == 401

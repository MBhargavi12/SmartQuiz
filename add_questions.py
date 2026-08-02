from app import app, db, Question

with app.app_context():
    questions = [
        Question(category="Programming", question_text="What is the output of print(2**3)?",
                  option_a="6", option_b="8", option_c="9", option_d="5", correct_option="B"),

        Question(category="Programming", question_text="Which keyword is used to define a function in Python?",
                  option_a="func", option_b="define", option_c="def", option_d="function", correct_option="C"),

        Question(category="DBMS", question_text="What does ACID stand for in DBMS?",
                  option_a="Atomicity, Consistency, Isolation, Durability",
                  option_b="Accuracy, Consistency, Integrity, Durability",
                  option_c="Atomicity, Concurrency, Isolation, Data",
                  option_d="None of these", correct_option="A"),

        Question(category="DBMS", question_text="Which of these is a primary key characteristic?",
                  option_a="Can be NULL", option_b="Can have duplicates",
                  option_c="Must be unique", option_d="Optional", correct_option="C"),

        Question(category="Aptitude", question_text="If a train travels 60 km in 1 hour, what is its speed?",
                  option_a="60 km/h", option_b="30 km/h", option_c="120 km/h", option_d="90 km/h", correct_option="A"),
    ]

    db.session.bulk_save_objects(questions)
    db.session.commit()

    print("✅ Sample questions added successfully!")
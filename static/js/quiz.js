let currentQuizId = null;

// 1. Requests new quiz from Flask backend and populates the UI
async function loadNewQuiz(topic = "Phishing", difficulty = "beginner") {
    try {
        const response = await fetch('/api/quiz/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic, difficulty })
        });

        const data = await response.json();

        if (data.success) {
            currentQuizId = data.quiz_id;

            // Render elements on screen
            document.getElementById('question-text').innerText = data.question;
            document.getElementById('opt-a-text').innerText = data.options.A;
            document.getElementById('opt-b-text').innerText = data.options.B;
            document.getElementById('opt-c-text').innerText = data.options.C;
            document.getElementById('opt-d-text').innerText = data.options.D;

            // Clear previous selections and results
            const checkedOption = document.querySelector('input[name="quiz-option"]:checked');
            if (checkedOption) checkedOption.checked = false;
            
            document.getElementById('feedback-box').innerText = '';
            document.getElementById('quiz-box').style.display = 'block';
        } else {
            alert("Error generating quiz: " + data.error);
        }
    } catch (err) {
        console.error("Fetch error:", err);
    }
}

// 2. Submits user selection and stores attempt in DB
async function submitAnswer() {
    const selectedRadio = document.querySelector('input[name="quiz-option"]:checked');

    if (!selectedRadio) {
        alert("Please select an answer option first!");
        return;
    }

    if (!currentQuizId) {
        alert("No active quiz found!");
        return;
    }

    const chosenOption = selectedRadio.value;

    try {
        const response = await fetch('/api/quiz/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                quiz_id: currentQuizId,
                answer: chosenOption
            })
        });

        const result = await response.json();

        if (result.success) {
            const feedbackBox = document.getElementById('feedback-box');
            if (result.is_correct) {
                feedbackBox.style.color = 'green';
                feedbackBox.innerText = `Correct! You selected (${result.submitted_answer}).`;
            } else {
                feedbackBox.style.color = 'red';
                feedbackBox.innerText = `Incorrect! You selected (${result.submitted_answer}). The correct answer was (${result.correct_option}).`;
            }
        }
    } catch (err) {
        console.error("Submission error:", err);
    }
}

// 3. Fetches stored history from database for display/review UI
async function loadQuizHistory() {
    try {
        const response = await fetch('/api/quiz/history');
        const resData = await response.json();

        if (resData.success) {
            const historyContainer = document.getElementById('history-container');
            historyContainer.innerHTML = '';

            resData.history.forEach(item => {
                const card = document.createElement('div');
                card.style.border = item.is_correct ? '2px solid green' : '2px solid red';
                card.style.margin = '10px 0';
                card.style.padding = '10px';

                card.innerHTML = `
                    <h4>Question: ${item.question}</h4>
                    <p>A: ${item.option_a}</p>
                    <p>B: ${item.option_b}</p>
                    <p>C: ${item.option_c}</p>
                    <p>D: ${item.option_d}</p>
                    <p><strong>Your Answer:</strong> ${item.user_chosen_option}</p>
                    <p><strong>Correct Answer:</strong> ${item.correct_option}</p>
                    <small>Attempted at: ${item.attempted_at}</small>
                `;
                historyContainer.appendChild(card);
            });
        }
    } catch (err) {
        console.error("History fetch error:", err);
    }
}
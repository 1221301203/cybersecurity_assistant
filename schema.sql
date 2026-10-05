-- Disable foreign key checks during schema creation
SET foreign_key_checks = 0;

-- Drop existing tables to ensure a clean setup
DROP TABLE IF EXISTS User_Reminders;
DROP TABLE IF EXISTS Cybersecurity_Tips;
DROP TABLE IF EXISTS Quiz_Results;
DROP TABLE IF EXISTS Quizzes;
DROP TABLE IF EXISTS Chatbot_Messages;
DROP TABLE IF EXISTS Chatbot_Sessions;
DROP TABLE IF EXISTS Users;

SET foreign_key_checks = 1;

-- 1. USERS TABLE (Table 4.1)
CREATE TABLE Users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_2fa_enabled BOOLEAN DEFAULT FALSE,
    preferred_language VARCHAR(10) DEFAULT 'en',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. CHATBOT_SESSIONS TABLE (Table 4.2)
CREATE TABLE Chatbot_Sessions (
    session_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) 
        REFERENCES Users(user_id) ON DELETE CASCADE
);

-- 3. CHATBOT_MESSAGES TABLE (Table 4.3)
CREATE TABLE Chatbot_Messages (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    sender ENUM('user', 'bot') NOT NULL,
    message_text TEXT NOT NULL,
    language_used VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id) 
        REFERENCES Chatbot_Sessions(session_id) ON DELETE CASCADE
);

-- 4. QUIZZES TABLE (Table 4.4)
CREATE TABLE Quizzes (
    quiz_id INT AUTO_INCREMENT PRIMARY KEY,
    difficulty_level ENUM('beginner', 'intermediate', 'advanced') NOT NULL,
    language VARCHAR(10) NOT NULL,
    question_text TEXT NOT NULL,
    option_a VARCHAR(255) NOT NULL,
    option_b VARCHAR(255) NOT NULL,
    option_c VARCHAR(255) NOT NULL,
    option_d VARCHAR(255) NOT NULL,
    correct_option CHAR(1) NOT NULL,
    explanation TEXT NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. QUIZ_RESULTS TABLE (Table 4.5)
CREATE TABLE Quiz_Results (
    result_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    quiz_id INT NOT NULL,
    user_answer CHAR(1) NOT NULL,
    is_correct BOOLEAN NOT NULL,
    attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_results_user FOREIGN KEY (user_id) 
        REFERENCES Users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_results_quiz FOREIGN KEY (quiz_id) 
        REFERENCES Quizzes(quiz_id) ON DELETE CASCADE
);

-- 6. CYBERSECURITY_TIPS TABLE (Table 4.6)
CREATE TABLE Cybersecurity_Tips (
    tip_id INT AUTO_INCREMENT PRIMARY KEY,
    language VARCHAR(10) NOT NULL,
    title VARCHAR(150) NOT NULL,
    content TEXT NOT NULL
);

-- 7. USER_REMINDERS TABLE (Table 4.7)
CREATE TABLE `user_reminders` (
  `user_reminder_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `tip_id` int(11) DEFAULT NULL,
  `title` varchar(255) NOT NULL,
  `description` text DEFAULT NULL,
  `type` varchar(50) DEFAULT NULL,
  `priority` varchar(50) NOT NULL,
  `is_completed` tinyint(1) DEFAULT 0,
  `completed_at` datetime DEFAULT NULL,
  `next_due_date` date NOT NULL,
  PRIMARY KEY (`user_reminder_id`),
  KEY `user_id` (`user_id`),
  KEY `tip_id` (`tip_id`),
  CONSTRAINT `user_reminders_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `user_reminders_ibfk_2` FOREIGN KEY (`tip_id`) REFERENCES `cybersecurity_tips` (`tip_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
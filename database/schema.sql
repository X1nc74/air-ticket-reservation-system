-- Complete InnoDB schema derived from the supplied course dump.
-- Import into an empty database; no customer records or password hashes are bundled.

CREATE TABLE `agent_works_for` (
  `email` varchar(100) NOT NULL,
  `airline_name` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `airline` (
  `airline_name` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `airline_staff` (
  `username` varchar(50) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `first_name` varchar(50) DEFAULT NULL,
  `last_name` varchar(50) DEFAULT NULL,
  `date_of_birth` date DEFAULT NULL,
  `airline_name` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `airplane` (
  `airplane_id` int(11) NOT NULL,
  `airline_name` varchar(50) NOT NULL,
  `model` varchar(50) DEFAULT NULL,
  `total_seats` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `airport` (
  `airport_code` char(3) NOT NULL,
  `name` varchar(100) NOT NULL,
  `city` varchar(50) NOT NULL,
  `country` varchar(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `booking_agent` (
  `email` varchar(100) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `agent_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `customer` (
  `email` varchar(100) NOT NULL,
  `name` varchar(100) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `building_number` varchar(10) DEFAULT NULL,
  `street` varchar(50) DEFAULT NULL,
  `city` varchar(50) DEFAULT NULL,
  `state` varchar(50) DEFAULT NULL,
  `phone_number` varchar(20) DEFAULT NULL,
  `passport_number` varchar(20) DEFAULT NULL,
  `passport_expiration` date DEFAULT NULL,
  `passport_country` varchar(50) DEFAULT NULL,
  `date_of_birth` date DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `flight` (
  `flight_id` int(11) NOT NULL,
  `airline_name` varchar(50) NOT NULL,
  `flight_num` varchar(10) NOT NULL,
  `departure_airport` char(3) NOT NULL,
  `departure_time` datetime NOT NULL,
  `arrival_airport` char(3) NOT NULL,
  `arrival_time` datetime NOT NULL,
  `base_price` decimal(10,2) NOT NULL,
  `status` enum('upcoming','delayed','in-progress','completed','cancelled') DEFAULT 'upcoming',
  `airplane_id` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `flight_seat_inventory` (
  `flight_id` int(11) NOT NULL,
  `class_code` varchar(10) NOT NULL,
  `capacity` int(11) NOT NULL,
  `base_price` decimal(10,2) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `purchases` (
  `ticket_id` int(11) NOT NULL,
  `customer_email` varchar(100) NOT NULL,
  `agent_email` varchar(100) DEFAULT NULL,
  `purchase_date` datetime NOT NULL,
  `sold_price` decimal(10,2) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `seat_class` (
  `class_code` varchar(10) NOT NULL,
  `description` varchar(100) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `staff_permission` (
  `username` varchar(50) NOT NULL,
  `permission_type` enum('admin','operator') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `ticket` (
  `ticket_id` int(11) NOT NULL,
  `flight_id` int(11) NOT NULL,
  `class_code` varchar(10) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE `agent_works_for`
  ADD PRIMARY KEY (`email`,`airline_name`),
  ADD KEY `airline_name` (`airline_name`);

ALTER TABLE `airline`
  ADD PRIMARY KEY (`airline_name`);

ALTER TABLE `airline_staff`
  ADD PRIMARY KEY (`username`),
  ADD KEY `airline_name` (`airline_name`);

ALTER TABLE `airplane`
  ADD PRIMARY KEY (`airplane_id`),
  ADD KEY `airline_name` (`airline_name`);

ALTER TABLE `airport`
  ADD PRIMARY KEY (`airport_code`);

ALTER TABLE `booking_agent`
  ADD PRIMARY KEY (`email`),
  ADD UNIQUE KEY `agent_id` (`agent_id`);

ALTER TABLE `customer`
  ADD PRIMARY KEY (`email`);

ALTER TABLE `flight`
  ADD PRIMARY KEY (`flight_id`),
  ADD UNIQUE KEY `uniq_flight` (`airline_name`,`flight_num`,`departure_time`),
  ADD KEY `airplane_id` (`airplane_id`),
  ADD KEY `departure_airport` (`departure_airport`),
  ADD KEY `idx_flight_departure` (`airline_name`,`departure_airport`,`departure_time`),
  ADD KEY `idx_flight_arrival` (`arrival_airport`,`arrival_time`);

ALTER TABLE `flight_seat_inventory`
  ADD PRIMARY KEY (`flight_id`,`class_code`),
  ADD KEY `class_code` (`class_code`);

ALTER TABLE `purchases`
  ADD PRIMARY KEY (`ticket_id`),
  ADD KEY `idx_purchases_date` (`purchase_date`),
  ADD KEY `idx_purchases_customer` (`customer_email`),
  ADD KEY `idx_purchases_agent` (`agent_email`);

ALTER TABLE `seat_class`
  ADD PRIMARY KEY (`class_code`);

ALTER TABLE `staff_permission`
  ADD PRIMARY KEY (`username`,`permission_type`);

ALTER TABLE `ticket`
  ADD PRIMARY KEY (`ticket_id`),
  ADD KEY `flight_id` (`flight_id`),
  ADD KEY `class_code` (`class_code`);

ALTER TABLE `airplane`
  MODIFY `airplane_id` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `booking_agent`
  MODIFY `agent_id` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `flight`
  MODIFY `flight_id` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `ticket`
  MODIFY `ticket_id` int(11) NOT NULL AUTO_INCREMENT;

ALTER TABLE `agent_works_for`
  ADD CONSTRAINT `agent_works_for_ibfk_1` FOREIGN KEY (`email`) REFERENCES `booking_agent` (`email`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `agent_works_for_ibfk_2` FOREIGN KEY (`airline_name`) REFERENCES `airline` (`airline_name`) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `airline_staff`
  ADD CONSTRAINT `airline_staff_ibfk_1` FOREIGN KEY (`airline_name`) REFERENCES `airline` (`airline_name`) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `airplane`
  ADD CONSTRAINT `airplane_ibfk_1` FOREIGN KEY (`airline_name`) REFERENCES `airline` (`airline_name`) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `flight`
  ADD CONSTRAINT `flight_ibfk_1` FOREIGN KEY (`airline_name`) REFERENCES `airline` (`airline_name`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `flight_ibfk_2` FOREIGN KEY (`airplane_id`) REFERENCES `airplane` (`airplane_id`) ON UPDATE CASCADE,
  ADD CONSTRAINT `flight_ibfk_3` FOREIGN KEY (`departure_airport`) REFERENCES `airport` (`airport_code`) ON UPDATE CASCADE,
  ADD CONSTRAINT `flight_ibfk_4` FOREIGN KEY (`arrival_airport`) REFERENCES `airport` (`airport_code`) ON UPDATE CASCADE;

ALTER TABLE `flight_seat_inventory`
  ADD CONSTRAINT `flight_seat_inventory_ibfk_1` FOREIGN KEY (`flight_id`) REFERENCES `flight` (`flight_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `flight_seat_inventory_ibfk_2` FOREIGN KEY (`class_code`) REFERENCES `seat_class` (`class_code`) ON UPDATE CASCADE;

ALTER TABLE `purchases`
  ADD CONSTRAINT `purchases_ibfk_1` FOREIGN KEY (`ticket_id`) REFERENCES `ticket` (`ticket_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `purchases_ibfk_2` FOREIGN KEY (`customer_email`) REFERENCES `customer` (`email`) ON UPDATE CASCADE,
  ADD CONSTRAINT `purchases_ibfk_3` FOREIGN KEY (`agent_email`) REFERENCES `booking_agent` (`email`) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE `staff_permission`
  ADD CONSTRAINT `staff_permission_ibfk_1` FOREIGN KEY (`username`) REFERENCES `airline_staff` (`username`) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `ticket`
  ADD CONSTRAINT `ticket_ibfk_1` FOREIGN KEY (`flight_id`) REFERENCES `flight` (`flight_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  ADD CONSTRAINT `ticket_ibfk_2` FOREIGN KEY (`class_code`) REFERENCES `seat_class` (`class_code`) ON UPDATE CASCADE;

ALTER TABLE airplane ADD CONSTRAINT chk_plane_seats CHECK (total_seats > 0);
ALTER TABLE flight ADD CONSTRAINT chk_flight_times CHECK (arrival_time > departure_time),
 ADD CONSTRAINT chk_flight_price CHECK (base_price >= 0);
ALTER TABLE flight_seat_inventory ADD CONSTRAINT chk_inventory_capacity CHECK (capacity >= 0),
 ADD CONSTRAINT chk_inventory_price CHECK (base_price >= 0);
ALTER TABLE purchases ADD CONSTRAINT chk_purchase_price CHECK (sold_price >= 0);
ALTER TABLE ticket ADD CONSTRAINT fk_ticket_inventory
 FOREIGN KEY (flight_id, class_code) REFERENCES flight_seat_inventory (flight_id, class_code);

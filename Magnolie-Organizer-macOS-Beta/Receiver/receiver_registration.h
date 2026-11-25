// SPDX-License-Identifier: GPL-3.0-or-later
// Bounded parser for UxPlay's legacy public-key registration file; Refs #721.
#ifndef MAGNOLIE_RECEIVER_REGISTRATION_H
#define MAGNOLIE_RECEIVER_REGISTRATION_H
#include <string>
#include <vector>

bool magnolie_valid_registration_key(const std::string &key);
bool magnolie_load_registration(const std::string &path, std::vector<std::string> &keys);
bool magnolie_save_registration(const std::string &path, const std::string &key);
#endif
